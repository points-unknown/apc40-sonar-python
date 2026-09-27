"""Unit tests for apc40sonar.hud_link (UDP publisher/receiver, HUD process)."""

from __future__ import annotations

import time

import pytest

from apc40sonar import hud_link
from apc40sonar.hud_state import HudSnapshot


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeSocket:
    def __init__(self, error: OSError | None = None) -> None:
        self.sent: list[tuple[bytes, tuple]] = []
        self.error = error
        self.closed = False

    def sendto(self, data, address):
        if self.error is not None:
            raise self.error
        self.sent.append((data, address))

    def close(self):
        self.closed = True


def make_publisher(**kwargs):
    clock = FakeClock()
    sock = FakeSocket(kwargs.pop("error", None))
    pub = hud_link.HudPublisher(47040, clock=clock, sock=sock, **kwargs)
    return pub, clock, sock


def test_encode_decode_round_trip():
    data = hud_link.encode(7, HudSnapshot(knob_mode="send_a"), {"mcu_in": True})
    payload = hud_link.decode(data)
    assert payload["seq"] == 7
    assert payload["info"] == {"mcu_in": True}
    assert payload["state"]["knob_mode"] == "send_a"
    assert len(data) < 4096


@pytest.mark.parametrize(
    "data",
    [b"not json", b"\xff\xfe", b"[1, 2]", b'{"v": 99, "state": {}}', b'{"v": 1, "state": 3}'],
)
def test_decode_rejects_malformed_datagrams(data):
    assert hud_link.decode(data) is None


def test_publisher_sends_on_change_with_a_rate_cap():
    pub, clock, sock = make_publisher(min_interval=0.05, heartbeat=1.0)
    a, b, c = HudSnapshot(), HudSnapshot(shift=True), HudSnapshot(loop=True)

    assert pub.publish(a)
    assert len(sock.sent) == 1
    assert sock.sent[0][1] == ("127.0.0.1", 47040)

    clock.now = 0.01
    assert not pub.due()
    assert not pub.publish(b)  # changed, but inside the 50 ms cap

    clock.now = 0.06
    assert pub.due()
    assert pub.publish(b)
    clock.now = 0.2
    assert not pub.publish(b)  # unchanged, heartbeat not due
    assert pub.publish(c)
    assert [hud_link.decode(d)["seq"] for d, _ in sock.sent] == [1, 2, 3]


def test_publisher_heartbeat_resends_unchanged_state():
    pub, clock, sock = make_publisher(min_interval=0.05, heartbeat=1.0)
    snap = HudSnapshot()
    pub.publish(snap)
    clock.now = 0.9
    assert not pub.publish(snap)
    clock.now = 1.0
    assert pub.publish(snap)
    assert len(sock.sent) == 2


@pytest.mark.parametrize("error", [ConnectionResetError(), OSError("boom")])
def test_publisher_swallows_socket_errors(error):
    pub, _clock, _sock = make_publisher(error=error)
    assert pub.publish(HudSnapshot())  # attempted, never raises


class FakeRecvSocket:
    def __init__(self, datagrams) -> None:
        self.datagrams = list(datagrams)

    def recv(self, _size):
        if not self.datagrams:
            raise BlockingIOError
        return self.datagrams.pop(0)


def test_receiver_keeps_the_newest_valid_payload():
    datagrams = [
        hud_link.encode(1, HudSnapshot(knob_mode="pan")),
        b"garbage",
        hud_link.encode(2, HudSnapshot(knob_mode="send_c")),
    ]
    receiver = hud_link.HudReceiver(0, sock=FakeRecvSocket(datagrams))
    assert receiver.poll()["state"]["knob_mode"] == "send_c"
    assert receiver.poll() is None


def test_publisher_to_receiver_over_loopback():
    receiver = hud_link.HudReceiver(0)
    port = receiver._sock.getsockname()[1]
    pub = hud_link.HudPublisher(port)
    try:
        pub.publish(HudSnapshot(transport="play"))
        payload = None
        for _ in range(100):
            payload = receiver.poll()
            if payload is not None:
                break
            time.sleep(0.01)
        assert payload is not None
        assert payload["state"]["transport"] == "play"
    finally:
        pub.close()
        receiver.close()


class FakeProc:
    pid = 1234

    def __init__(self, code=None) -> None:
        self.code = code
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class FakePopen:
    def __init__(self) -> None:
        self.procs: list[FakeProc] = []

    def __call__(self, argv, **kwargs):
        proc = FakeProc()
        self.procs.append(proc)
        return proc


def test_hud_process_respawns_with_backoff_then_gives_up():
    popen, clock = FakePopen(), FakeClock()
    hud = hud_link.HudProcess(["hud"], max_restarts=2, backoff=1.0, popen=popen, clock=clock)
    hud.start()
    assert len(popen.procs) == 1

    popen.procs[-1].code = 1  # crash
    hud.poll()
    hud.poll()
    assert len(popen.procs) == 1  # waiting out the backoff
    clock.now = 1.0
    hud.poll()
    assert len(popen.procs) == 2

    popen.procs[-1].code = 1
    hud.poll()
    clock.now = 2.9
    hud.poll()
    assert len(popen.procs) == 2  # second backoff is 2 s
    clock.now = 3.0
    hud.poll()
    assert len(popen.procs) == 3

    popen.procs[-1].code = 1
    clock.now = 100.0
    hud.poll()
    hud.poll()
    assert len(popen.procs) == 3  # gave up after max_restarts


def test_hud_process_quit_by_the_user_is_not_respawned():
    popen, clock = FakePopen(), FakeClock()
    hud = hud_link.HudProcess(["hud"], popen=popen, clock=clock)
    hud.start()
    popen.procs[-1].code = 0
    hud.poll()
    clock.now = 100.0
    hud.poll()
    assert len(popen.procs) == 1


def test_hud_process_stop_terminates_the_child():
    popen = FakePopen()
    hud = hud_link.HudProcess(["hud"], popen=popen)
    hud.start()
    hud.stop()
    assert popen.procs[0].terminated
    hud.poll()
    assert len(popen.procs) == 1


def test_hud_process_start_failure_is_not_fatal():
    def failing(argv, **kwargs):
        raise OSError("no python")

    hud = hud_link.HudProcess(["hud"], popen=failing)
    assert not hud.start()
    hud.poll()
