"""Нормализация распознанной речи и подготовка ответа к синтезу."""

from __future__ import annotations

from core import text as text_utils


def test_address_is_stripped() -> None:
    assert text_utils.normalize("Юки, открой телеграм") == "открой телеграм"


def test_polite_words_are_stripped() -> None:
    assert text_utils.normalize("Юки, пожалуйста открой хром") == "открой хром"


def test_wake_name_survives_misrecognition() -> None:
    for spoken in ("джарис", "атлаз", "юки"):
        assert text_utils.wake_name(spoken) is not None


def test_wake_name_ignores_random_words() -> None:
    assert text_utils.wake_name("погода завтра") is None


def test_strip_wake_handles_split_name() -> None:
    assert text_utils.strip_wake("Джар вис открой хром") == "открой хром"


def test_addressed_detects_call_by_name() -> None:
    assert text_utils.addressed("Юки, который час")
    assert not text_utils.addressed("который час")


def test_clean_reply_drops_markdown_and_links() -> None:
    cleaned = text_utils.clean_reply("**Готово** — смотри https://example.com")
    assert "**" not in cleaned
    assert "https://" not in cleaned


def test_clean_reply_drops_foreign_script() -> None:
    assert "字幕" not in text_utils.clean_reply("Готово 字幕")


def test_for_speech_respects_length_limit() -> None:
    long_text = "Очень длинный ответ. " * 60
    assert len(text_utils.for_speech(long_text)) <= text_utils.SPEECH_LIMIT


def test_soften_removes_support_desk_cliches() -> None:
    assert "чем могу помочь" not in text_utils.soften("Чем могу помочь вам?").lower()
