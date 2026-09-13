"""Unit tests for apc40sonar.midi_io (no MIDI hardware required)."""

from __future__ import annotations

import pytest

from apc40sonar import midi_io


def test_strip_index_removes_trailing_index():
    assert midi_io.strip_index("APC40-MCU 1") == "APC40-MCU"


def test_strip_index_keeps_name_without_index():
    assert midi_io.strip_index("Akai APC40") == "Akai APC40"


def test_strip_index_keeps_trailing_non_numeric():
    assert midi_io.strip_index("Port 2 X") == "Port 2 X"


def test_resolve_index_exact_match_is_case_insensitive():
    names = ["APC40-MCU 0", "Akai APC40 3"]
    assert midi_io.resolve_index(names, "akai apc40") == 1


def test_resolve_index_accepts_configured_plain_name():
    # Config uses the plain documented name; rtmidi reports a suffixed one.
    names = ["Microsoft GS Wavetable Synth 0", "APC40-DEBUG 2"]
    assert midi_io.resolve_index(names, "APC40-DEBUG") == 1


def test_resolve_index_falls_back_to_unique_substring():
    names = ["Microsoft GS Wavetable Synth 0", "My Debug Cable 1"]
    assert midi_io.resolve_index(names, "debug") == 1


def test_resolve_index_missing_reports_available_ports():
    with pytest.raises(LookupError) as excinfo:
        midi_io.resolve_index(["Akai APC40 0"], "APC40-MCU")
    message = str(excinfo.value)
    assert "APC40-MCU" in message
    assert "Akai APC40" in message


def test_resolve_index_ambiguous_substring_raises():
    names = ["APC40-MCU 0", "APC40-DEBUG 1"]
    with pytest.raises(LookupError):
        midi_io.resolve_index(names, "APC40")
