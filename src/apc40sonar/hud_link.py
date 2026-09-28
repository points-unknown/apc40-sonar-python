"""HUD transport: UDP JSON snapshots on 127.0.0.1 and the HUD child process.

The only HUD code that does I/O. The engine side (:class:`HudPublisher`) does
one non-blocking ``sendto`` at most every ``min_interval`` seconds and swallows
every socket error, so a missing, slow or crashed HUD can never stall MIDI.
Each datagram is a full snapshot, so a lost packet is harmless.

Wire format (UTF-8 JSON, one object per datagram)::

    {"v": 1, "seq": 42, "info": {...}, "state": {HudSnapshot fields}}
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import time
from typing import Callable, Sequence

from . import hud_state

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
PROTOCOL_VERSION = 1
MAX_DATAGRAM = 65507


def encode(seq: int, snapshot: hud_state.HudSnapshot, info: dict | None = None) -> bytes:
    payload = {
        "v": PROTOCOL_VERSION,
        "seq": seq,
        "info": info or {},
        "state": hud_state.to_dict(snapshot),
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> dict | None:
    """Parse one datagram; ``None`` for anything malformed or from another version."""

    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != PROTOCOL_VERSION:
        return None
    if not isinstance(payload.get("state"), dict):
        return None
    return payload


class HudPublisher:
    """Send engine snapshots to the HUD: on change, rate-capped, plus a heartbeat."""

    def __init__(
        self,
        port: int,
        *,
        host: str = HOST,
        min_interval: float = 0.05,
        heartbeat: float = 1.0,
        info: dict | None = None,
        clock: Callable[[], float] = time.monotonic,
        sock: socket.socket | None = None,
    ) -> None:
        self.address = (host, port)
        self.min_interval = min_interval
        self.heartbeat = heartbeat
        self.info = dict(info or {})
        self._clock = clock
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
        self._sock = sock
        self._last: hud_state.HudSnapshot | None = None
        self._last_time: float | None = None
        self._seq = 0
        self._error_logged = False

    def due(self) -> bool:
        """True when a send is allowed now; callers skip building a snapshot otherwise."""

        last = self._last_time
        return last is None or self._clock() - last >= self.min_interval

    def publish(self, snapshot: hud_state.HudSnapshot) -> bool:
        """Send *snapshot* if it changed (and the rate cap allows) or a heartbeat is due."""

        now = self._clock()
        last = self._last_time
        if last is not None:
            elapsed = now - last
            if elapsed < self.min_interval:
                return False
            if snapshot == self._last and elapsed < self.heartbeat:
                return False
        self._seq += 1
        self._last = snapshot
        self._last_time = now
        data = encode(self._seq, snapshot, self.info)
        try:
            self._sock.sendto(data, self.address)
        except OSError as exc:
            # Windows reports an earlier datagram to a closed port as
            # ConnectionResetError on a later send; nobody listening is normal.
            if not self._error_logged and not isinstance(exc, ConnectionResetError):
                log.warning("HUD send failed: %s", exc)
                self._error_logged = True
        return True

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class HudReceiver:
    """HUD side: a non-blocking UDP socket that keeps only the newest snapshot."""

    def __init__(self, port: int, *, host: str = HOST, sock: socket.socket | None = None) -> None:
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if sys.platform == "win32" and hasattr(socket, "SIO_UDP_CONNRESET"):
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            sock.bind((host, port))
            sock.setblocking(False)
        self._sock = sock

    def poll(self) -> dict | None:
        """Drain the socket; return the newest valid payload, or ``None``."""

        newest = None
        while True:
            try:
                data = self._sock.recv(MAX_DATAGRAM)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            payload = decode(data)
            if payload is not None:
                newest = payload  # loopback UDP keeps order; the last one wins
        return newest

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class HudProcess:
    """Run the HUD as a child process; respawn with backoff if it exits.

    The HUD is optional: a failure to start or repeated crashes are logged
    and the app carries on without it.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        max_restarts: int = 3,
        backoff: float = 2.0,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        name: str = "HUD",
    ) -> None:
        self.name = name
        self.argv = list(argv)
        self.max_restarts = max_restarts
        self.backoff = backoff
        self._popen = popen
        self._clock = clock
        self._proc: subprocess.Popen | None = None
        self._restarts = 0
        self._retry_at: float | None = None
        self._stopped = False

    def start(self) -> bool:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._proc = self._popen(self.argv, **kwargs)
        except OSError as exc:
            log.warning("cannot start the %s: %s", self.name, exc)
            self._proc = None
            return False
        log.info("%s started (pid %s)", self.name, getattr(self._proc, "pid", "?"))
        return True

    def poll(self) -> None:
        """Respawn an exited HUD, at most *max_restarts* times, never blocking."""

        if self._stopped:
            return
        now = self._clock()
        if self._proc is not None:
            code = self._proc.poll()
            if code is None:
                return
            self._proc = None
            if code == 0:
                # Quit from its own menu: the user closed it on purpose.
                log.info("%s closed", self.name)
                self._stopped = True
                return
            log.warning("%s exited with code %s", self.name, code)
            if self._restarts >= self.max_restarts:
                log.warning("%s gave up after %d restarts", self.name, self._restarts)
                self._stopped = True
                return
            self._retry_at = now + self.backoff * (2 ** self._restarts)
            return
        if self._retry_at is not None and now >= self._retry_at:
            self._retry_at = None
            self._restarts += 1
            self.start()

    def stop(self) -> None:
        self._stopped = True
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001 - best effort on shutdown
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
