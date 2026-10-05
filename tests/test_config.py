"""Unit tests for apc40sonar.config (dynamic port-name loading)."""

from __future__ import annotations

from pathlib import Path

import pytest

from apc40sonar import config


def _clear_port_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in config.DEFAULTS:
        monkeypatch.delenv(key, raising=False)


def test_parse_env_basic_and_quoting():
    text = "\n".join(
        [
            "# a comment",
            "",
            "APC40_PORT=Akai APC40",
            'MCU_OUT_PORT = "APC40-IN"',
            "export MCU_IN_PORT='APC40-OUT'",
            "this line has no equals sign",
            "   ",
        ]
    )
    values = config.parse_env(text)
    assert values == {
        "APC40_PORT": "Akai APC40",
        "MCU_OUT_PORT": "APC40-IN",
        "MCU_IN_PORT": "APC40-OUT",
    }


def test_load_config_uses_defaults_when_no_env(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)
    cfg = config.load_config(env_path=tmp_path / "missing.env")
    assert cfg.apc40_port == "Akai APC40"
    assert cfg.mcu_out_port == "APC40-IN"
    assert cfg.mcu_in_port == "APC40-OUT"
    assert cfg.client_name == "apc40sonar"
    assert cfg.env_path is None


def test_load_config_reads_values_from_file(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("APC40_PORT=My APC40\nMCU_OUT_PORT=Cable A\n", encoding="utf-8")

    cfg = config.load_config(env_path=env_file)
    assert cfg.apc40_port == "My APC40"
    assert cfg.mcu_out_port == "Cable A"
    # Unspecified key keeps its default.
    assert cfg.mcu_in_port == "APC40-OUT"
    assert cfg.env_path == env_file


def test_process_environment_overrides_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APC40_PORT=From File\n", encoding="utf-8")
    monkeypatch.setenv("APC40_PORT", "From Env")

    cfg = config.load_config(env_path=env_file)
    assert cfg.apc40_port == "From Env"


def test_find_env_file_honors_override(tmp_path):
    target = tmp_path / "custom.env"
    target.write_text("APC40_PORT=X\n", encoding="utf-8")

    found = config.find_env_file(cwd=tmp_path, environ={config.ENV_VAR: str(target)})
    assert found == target


def test_find_env_file_autodetects_cwd(tmp_path):
    target = tmp_path / ".env"
    target.write_text("APC40_PORT=X\n", encoding="utf-8")

    found = config.find_env_file(cwd=tmp_path, environ={})
    assert found == target


def test_find_env_file_returns_none_when_absent(tmp_path):
    assert config.find_env_file(cwd=tmp_path, environ={}) is None


def test_apc40_mode_defaults_and_overrides(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    assert config.load_config(env_path=tmp_path / "missing.env").apc40_mode == "generic"

    env_file = tmp_path / ".env"
    env_file.write_text("APC40_MODE=ableton\n", encoding="utf-8")
    assert config.load_config(env_path=env_file).apc40_mode == "ableton"


def test_knob_step_limit_default_and_override(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    assert config.load_config(env_path=tmp_path / "missing.env").knob_step_limit == 3

    env_file = tmp_path / ".env"
    env_file.write_text("KNOB_STEP_LIMIT=1\n", encoding="utf-8")
    assert config.load_config(env_path=env_file).knob_step_limit == 1


def test_knob_step_limit_invalid_falls_back_to_default(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("KNOB_STEP_LIMIT=abc\n", encoding="utf-8")
    assert config.load_config(env_path=env_file).knob_step_limit == 3


def test_knob_noise_threshold_default_and_override(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    assert config.load_config(env_path=tmp_path / "missing.env").knob_noise_threshold == 4

    env_file = tmp_path / ".env"
    env_file.write_text("KNOB_NOISE_THRESHOLD=0\n", encoding="utf-8")
    assert config.load_config(env_path=env_file).knob_noise_threshold == 0


def test_meters_default_on_and_accept_on_off_words(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    cfg = config.load_config(env_path=tmp_path / "missing.env")
    assert cfg.meters is True
    assert cfg.meter_decay_ms == 300

    env_file = tmp_path / ".env"
    env_file.write_text("METERS=off\nMETER_DECAY_MS=150\n", encoding="utf-8")
    cfg = config.load_config(env_path=env_file)
    assert cfg.meters is False
    assert cfg.meter_decay_ms == 150

    env_file.write_text("METERS=maybe\n", encoding="utf-8")
    assert config.load_config(env_path=env_file).meters is True


def test_zoom_settings_default_and_override(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    cfg = config.load_config(env_path=tmp_path / "missing.env")
    assert (cfg.zoom_step_units, cfg.zoom_idle_ms) == (6, 300)

    env_file = tmp_path / ".env"
    env_file.write_text("ZOOM_STEP_UNITS=4\nZOOM_IDLE_MS=500\n", encoding="utf-8")
    cfg = config.load_config(env_path=env_file)
    assert (cfg.zoom_step_units, cfg.zoom_idle_ms) == (4, 500)


def test_hud_settings_defaults(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    cfg = config.load_config(env_path=tmp_path / "missing.env")
    assert cfg.hud is True
    assert cfg.hud_port == 47040
    assert cfg.hud_position == "top-right"
    assert cfg.hud_monitor == 0
    assert cfg.hud_opacity == 0.85
    assert cfg.hud_topmost is True
    assert cfg.hud_click_through is False
    assert cfg.hud_layout == "compact"
    assert cfg.hud_toast_ms == 1200
    assert cfg.hud_lcd is True


def test_hud_settings_override_and_validation(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "HUD=off",
                "HUD_PORT=50000",
                "HUD_POSITION=Bottom-Left",
                "HUD_MONITOR=1",
                "HUD_OPACITY=0.05",
                "HUD_TOPMOST=off",
                "HUD_CLICK_THROUGH=yes",
                "HUD_LAYOUT=Expanded",
                "HUD_TOAST_MS=800",
                "HUD_LCD=off",
            ]
        ),
        encoding="utf-8",
    )
    cfg = config.load_config(env_path=env_file)
    assert cfg.hud is False
    assert cfg.hud_port == 50000
    assert cfg.hud_position == "bottom-left"
    assert cfg.hud_monitor == 1
    assert cfg.hud_opacity == 0.2  # clamped
    assert cfg.hud_topmost is False
    assert cfg.hud_click_through is True
    assert cfg.hud_layout == "expanded"
    assert cfg.hud_toast_ms == 800
    assert cfg.hud_lcd is False

    env_file.write_text("HUD_OPACITY=abc\nHUD_LAYOUT=huge\n", encoding="utf-8")
    cfg = config.load_config(env_path=env_file)
    assert (cfg.hud_opacity, cfg.hud_layout) == (0.85, "compact")


def test_playhead_steps_default_and_override(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    cfg = config.load_config(env_path=tmp_path / "missing.env")
    assert cfg.cue_step == (1, "beat")
    assert cfg.shift_cue_step == (30, "tick")
    assert cfg.nudge_step == (1, "measure")
    assert cfg.nudge_repeat_ms == 150

    env_file = tmp_path / ".env"
    env_file.write_text(
        "CUE_STEP=2 beats\nSHIFT_CUE_STEP=40 ticks\nNUDGE_STEP=measure\nNUDGE_REPEAT_MS=100\n",
        encoding="utf-8",
    )
    cfg = config.load_config(env_path=env_file)
    assert (cfg.cue_step, cfg.shift_cue_step, cfg.nudge_step) == ((2, "beat"), (40, "tick"), (1, "measure"))
    assert cfg.nudge_repeat_ms == 100


def test_invalid_playhead_step_falls_back_to_default(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("CUE_STEP=3 bars\nNUDGE_STEP=0 beat\n", encoding="utf-8")

    cfg = config.load_config(env_path=env_file)

    assert cfg.cue_step == (1, "beat")
    assert cfg.nudge_step == (1, "measure")


def test_parse_step_forms():
    assert config.parse_step("1 beat") == (1, "beat")
    assert config.parse_step("30 Ticks") == (30, "tick")
    assert config.parse_step("measure") == (1, "measure")
    assert config.parse_step("jog") == (1, "jog")
    assert config.parse_step("49 tick") is None  # capped: flood risk
    assert config.parse_step("") is None



def test_sequencer_settings_defaults(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    monkeypatch.delenv(config.ENV_VAR, raising=False)

    cfg = config.load_config(env_path=tmp_path / "missing.env")
    assert cfg.seq_out_port == "APC40-SEQ"
    assert cfg.clock_in_port == "APC40-CLOCK"
    assert cfg.seq_notes == (36, 38, 42, 46, 39, 37, 45, 47, 50, 49)
    assert cfg.seq_channel == 10
    assert cfg.seq_steps == 16
    assert cfg.seq_velocities == (100, 127, 60)


def test_sequencer_settings_override_and_validation(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SEQ_NOTES=36, 38 42\nSEQ_CHANNEL=1\nSEQ_STEPS=32\nSEQ_VELOCITIES=90 120 40\n",
        encoding="utf-8",
    )
    cfg = config.load_config(env_path=env_file)
    assert cfg.seq_notes == (36, 38, 42)
    assert cfg.seq_channel == 1
    assert cfg.seq_steps == 32
    assert cfg.seq_velocities == (90, 120, 40)

    env_file.write_text(
        "SEQ_NOTES=36 200\nSEQ_CHANNEL=17\nSEQ_STEPS=0\nSEQ_VELOCITIES=90 120\n",
        encoding="utf-8",
    )
    cfg = config.load_config(env_path=env_file)
    assert cfg.seq_notes == (36, 38, 42, 46, 39, 37, 45, 47, 50, 49)
    assert cfg.seq_channel == 16
    assert cfg.seq_steps == 1
    assert cfg.seq_velocities == (100, 127, 60)


def test_sequencer_editor_settings(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("SEQ_EDITOR=off\nSEQ_EDITOR_PORT=50001\nSEQ_DIR=my patterns\n", encoding="utf-8")

    cfg = config.load_config(env_path=env_file)

    assert cfg.seq_editor is False
    assert cfg.seq_editor_port == 50001
    assert cfg.seq_dir == tmp_path / "my patterns"  # relative to the .env folder


def test_c4_keys_default_and_override(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    cfg = config.load_config(env_path=tmp_path / "missing.env")
    assert (cfg.c4_out_port, cfg.c4_in_port) == ("C4-IN", "C4-OUT")
    assert cfg.c4 and cfg.c4_reset_on_select and cfg.c4_knob_step_limit == 3

    env_file = tmp_path / ".env"
    env_file.write_text("C4=off\nC4_KNOB_STEP_LIMIT=99\nC4_RESET_ON_SELECT=no\nC4_OUT_PORT=X\n", encoding="utf-8")
    cfg = config.load_config(env_path=env_file)
    assert not cfg.c4 and not cfg.c4_reset_on_select
    assert cfg.c4_knob_step_limit == 15  # the C4's top speed
    assert cfg.c4_out_port == "X"


def test_hud_margin_default_and_override(tmp_path, monkeypatch):
    _clear_port_env(monkeypatch)
    assert config.load_config(env_path=tmp_path / "missing.env").hud_margin == (50, 12)
    env_file = tmp_path / ".env"
    for text, expected in (("80,0", (80, 0)), ("30", (30, 30)), ("junk", (50, 12))):
        env_file.write_text(f"HUD_MARGIN={text}\n", encoding="utf-8")
        assert config.load_config(env_path=env_file).hud_margin == expected
