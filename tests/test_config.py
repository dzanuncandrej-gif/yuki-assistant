"""Конфигурация: умолчания, слияние, переменные окружения, запись раздела."""

from __future__ import annotations

import json

from core import config


def test_defaults_cover_every_section_used_by_the_app() -> None:
    for section in ("audio", "stt", "tts", "brain", "live", "ui", "companion",
                    "account", "camera", "files", "web", "wake", "server"):
        assert section in config.DEFAULTS, f"раздел {section} пропал из умолчаний"


def test_security_defaults_are_conservative() -> None:
    """Сеть и выход за домашнюю папку по умолчанию выключены."""
    assert config.DEFAULTS["tts"]["allow_cloud_voice"] is False
    assert config.DEFAULTS["files"]["restrict_paths"] is False
    assert config.DEFAULTS["server"]["host"] == "127.0.0.1"


def test_example_config_matches_default_sections() -> None:
    example = json.loads((config.ROOT / "config.example.json").read_text(encoding="utf-8"))
    for section in example:
        assert section in config.DEFAULTS, f"в примере есть лишний раздел {section}"


def test_example_config_has_no_personal_data() -> None:
    example = json.loads((config.ROOT / "config.example.json").read_text(encoding="utf-8"))
    assert example["account"]["name"] == ""
    assert example["account"]["handle"] == ""
    assert example["contacts"] == {}


def test_merge_keeps_untouched_defaults(tmp_path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"brain": {"model": "custom:1b"}}), encoding="utf-8")
    loaded = config.load(target)
    assert loaded["brain"]["model"] == "custom:1b"
    assert loaded["brain"]["num_ctx"] == config.DEFAULTS["brain"]["num_ctx"]


def test_save_section_writes_only_that_section(tmp_path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"tts": {"voice": "sora"}, "ui": {"accent": "aqua"}}), encoding="utf-8")
    config.save_section("tts", {"voice": "mira"}, target)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["tts"]["voice"] == "mira"
    assert saved["ui"]["accent"] == "aqua"


def test_env_placeholder_is_expanded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("YUKI_TEST_KEY", "секрет")
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"web": {"default_city": "${YUKI_TEST_KEY}"}}), encoding="utf-8")
    assert config.load(target)["web"]["default_city"] == "секрет"
