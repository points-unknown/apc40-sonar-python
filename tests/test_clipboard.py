from pathlib import Path

from apc40sonar import clipboard as cb
from apc40sonar import midi_file as mf
from apc40sonar import sequencer as sq

# A clip copied in Sonar, as read from its "Standard MIDI File" clipboard format
# (960 PPQ, format 1, padded by GlobalSize).
SONAR_COPY = Path(__file__).with_name("sonar_clipboard.mid")


def test_rmid_unwrap():
    smf = mf.to_midi_bytes({"steps": 1, "lanes": [{"note": 36, "channel": 10, "steps": [100]}]}, 1)
    pad = b"\x00" if len(smf) % 2 else b""
    chunk = b"data" + len(smf).to_bytes(4, "little") + smf + pad
    riff = b"RIFF" + (4 + len(chunk)).to_bytes(4, "little") + b"RMID" + chunk

    assert cb.unwrap_rmid(riff) == smf
    assert cb.unwrap_rmid(b"not riff") is None


def test_sonar_clipboard_copy_imports():
    seq = sq.Sequencer(lambda m: None)

    pattern, summary = mf.import_pattern(SONAR_COPY.read_bytes(), seq.to_dict())

    assert summary.startswith("16 notes")
    assert seq.load_dict(pattern)


def test_sonar_copy_on_the_1_lands_on_step_one_as_one_bar():
    seq = sq.Sequencer(lambda m: None)
    data = SONAR_COPY.with_name("sonar_clipboard_on_the_1.mid").read_bytes()

    pattern, summary = mf.import_pattern(data, seq.to_dict())

    assert pattern["steps"] == 16 and "repeats every 1 bar" in summary
    hits = {lane["note"] for lane in pattern["lanes"] if lane["steps"] == [100] + [0] * 15}
    assert hits == {36, 38, 39, 42}
