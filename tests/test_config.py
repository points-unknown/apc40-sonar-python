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
