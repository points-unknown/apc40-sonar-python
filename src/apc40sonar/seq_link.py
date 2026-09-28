"""Sequencer editor link: UDP JSON on 127.0.0.1 between the app and the editor window.

Two one-way channels, both small datagrams:

* app -> editor (``port``): the whole pattern plus playhead and APC40 page,
  ``{"v": 1, "state": {...}}``, sent on change and as a heartbeat. A lost
  packet is harmless: the next one is complete.
* editor -> app (``port + 1``): edit commands, ``{"v": 1, "cmd": {"op": ...}}``,
  applied on the app's run loop so the APC40 LEDs follow at once.

Like the HUD link, the app side never blocks and swallows socket errors, so a
missing or crashed editor can never stall MIDI.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from typing import Callable

HOST = "127.0.0.1"
PROTOCOL_VERSION = 1
MAX_DATAGRAM = 65507


def encode(kind: str, body: dict) -> bytes:
    return json.dumps({"v": PROTOCOL_VERSION, kind: body}, separators=(",", ":")).encode("utf-8")


def decode(data: bytes, kind: str) -> dict | None:
    """The *kind* body of one datagram; None for anything malformed."""

    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != PROTOCOL_VERSION:
        return None
    body = payload.get(kind)
    return body if isinstance(body, dict) else None


class Sender:
    """Fire-and-forget datagrams to one local port."""

    def __init__(self, port: int, *, host: str = HOST, sock: socket.socket | None = None) -> None:
        self.address = (host, port)
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
        self._sock = sock

    def send(self, kind: str, body: dict) -> None:
        try:
            self._sock.sendto(encode(kind, body), self.address)
        except OSError:
            pass  # nobody listening (the editor is closed) is normal

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class Receiver:
    """A bound, non-blocking UDP socket."""

    def __init__(self, port: int, *, host: str = HOST, sock: socket.socket | None = None) -> None:
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if sys.platform == "win32" and hasattr(socket, "SIO_UDP_CONNRESET"):
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            sock.bind((host, port))
            sock.setblocking(False)
        self._sock = sock

    def poll(self, kind: str) -> list[dict]:
        """Every valid *kind* body waiting on the socket, oldest first."""

        bodies = []
        while True:
            try:
                data = self._sock.recv(MAX_DATAGRAM)
            except OSError:  # BlockingIOError when empty
                break
            body = decode(data, kind)
            if body is not None:
                bodies.append(body)
        return bodies

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class StatePublisher:
    """App side: send the editor state when it changes (rate-capped) or as a heartbeat."""

    def __init__(
        self,
        sender: Sender,
        *,
        min_interval: float = 0.03,
        heartbeat: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sender = sender
        self.min_interval = min_interval
        self.heartbeat = heartbeat
        self._clock = clock
        self._last: dict | None = None
        self._last_time: float | None = None

    def publish(self, state: dict) -> bool:
        now = self._clock()
        last = self._last_time
        if last is not None:
            elapsed = now - last
            if elapsed < self.min_interval:
                return False
            if state == self._last and elapsed < self.heartbeat:
                return False
        self._last = state
        self._last_time = now
        self.sender.send("state", state)
        return True

    def reset(self) -> None:
        """Send the next state at once (a new editor window just opened)."""

        self._last = None
        self._last_time = None
