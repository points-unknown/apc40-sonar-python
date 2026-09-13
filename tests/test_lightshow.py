"""Unit tests for apc40sonar.lightshow (frame generation, no timing)."""

from __future__ import annotations

from apc40sonar import apc40 as apc
from apc40sonar import lightshow


def test_light_everything_addresses_every_host_led_and_both_ring_banks():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)

    lightshow.light_everything(out)

    note_on = [m for m in sent if (m[0] & 0xF0) == 0x90]
    cc = [m for m in sent if (m[0] & 0xF0) == 0xB0]

    # 8 tracks * (5 pads + 1 clip stop + 4 strip LEDs) = 80
    # + utility 8 + scenes 5 + master 1 + transport 3 + pan/send 4 = 101
    assert len(note_on) == 101
    # 8 knobs * (track position + track style + device position + device style) = 32
    assert len(cc) == 32


def test_play_runs_all_frames_and_ends_dark():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)
    seen: list[int] = []

    lightshow.play(out, sleep=lambda _seconds: None, on_frame=seen.append)

    # 1 clear + 6 color chase + 5 ring sweep + 1 all-on + 1 final clear
    assert len(seen) == 14
    assert sent[-1][2] == 0  # last write is an off


def test_frame_count_is_stable():
    assert len(list(lightshow.frames())) == 14
