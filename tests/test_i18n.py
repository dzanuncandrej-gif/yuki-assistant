"""Перевод интерфейса: английский режим не должен терять надписи."""

from __future__ import annotations

import pytest

from core import i18n


@pytest.fixture(autouse=True)
def _restore_language():
    before = i18n.active()
    yield
    i18n.set_active(before)


def test_russian_leaves_text_as_is() -> None:
    i18n.set_active("ru")
    assert i18n.t("Голос ассистента") == "Голос ассистента"


def test_english_translates_known_labels() -> None:
    i18n.set_active("en")
    assert i18n.t("Голос ассистента") == "Assistant voice"
    assert i18n.t("ВЫПОЛНИТЬ") == "RUN"
    assert i18n.t("ОЖИДАНИЕ") == "IDLE"


def test_unknown_string_falls_back_to_original() -> None:
    i18n.set_active("en")
    assert i18n.t("Совершенно новая подпись") == "Совершенно новая подпись"


def test_unsupported_language_falls_back_to_default() -> None:
    i18n.set_active("de")
    assert i18n.active() == i18n.DEFAULT


def test_translations_are_not_empty_and_differ() -> None:
    """Пустой или совпадающий перевод — забытая строка, а не перевод."""
    for source, translated in i18n._EN.items():
        assert translated.strip(), f"пустой перевод для «{source}»"
        if source not in ("ENGLISH", "BASE", "MEDIUM"):
            assert translated != source, f"строка «{source}» не переведена"
