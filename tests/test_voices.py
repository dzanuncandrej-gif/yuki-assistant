"""Каталог голосов: ключи, английские голоса, разрешение имени вслух."""

from __future__ import annotations

from core import voices


def test_keys_are_unique() -> None:
    keys = [profile.key for profile in voices.catalog()]
    assert len(keys) == len(set(keys))


def test_every_profile_has_russian_and_english_voice() -> None:
    for profile in voices.catalog():
        assert profile.edge_voice.startswith("ru-"), f"{profile.key}: русский голос не задан"
        assert profile.edge_voice_en.startswith("en-"), f"{profile.key}: английский голос не задан"


def test_companion_keys_exist_in_catalog() -> None:
    known = {profile.key for profile in voices.catalog()}
    for key in voices.COMPANION_KEYS:
        assert key in known, f"голос компаньона {key} отсутствует в каталоге"


def test_default_profile_is_in_catalog() -> None:
    assert voices.get(voices.DEFAULT) is not None


def test_resolve_understands_spoken_forms() -> None:
    assert voices.resolve("атлас").key == "atlas"
    assert voices.resolve("ауру").key == "aura"
    assert voices.resolve("sora").key == "sora"


def test_resolve_rejects_unknown_name() -> None:
    try:
        voices.resolve("чебурашка")
    except voices.VoiceError as err:
        assert "чебурашка" in str(err)
    else:  # pragma: no cover — ветка нужна только если поведение изменится
        raise AssertionError("неизвестный голос должен приводить к VoiceError")


def test_aliases_point_to_existing_profiles() -> None:
    known = {profile.key for profile in voices.catalog()}
    for alias, key in voices.ALIASES.items():
        assert key in known, f"псевдоним «{alias}» ведёт в никуда: {key}"
