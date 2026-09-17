"""Переключение рабочего языка: распознавание речи, голос синтеза и язык ответа модели —
одной командой («говори по-английски» / «switch to english»).

Не входит сюда: перевод готовых фраз командного слоя (core/commands.py и другие) —
там сотни литеральных русских строк-ответов вида «Открыла.», и это отдельная большая
работа. Переключение здесь покрывает распознавание речи, свободный ответ модели и
голос — то есть разговор с ассистентом, а не текст подтверждений команд.
"""

from __future__ import annotations

from typing import Any

LANGUAGES = ("ru", "en")
DEFAULT = "ru"

NAMES = {"ru": "русский", "en": "английский"}

SPEECH_RULES: dict[str, str] = {
    "ru": (
        "Речь: только русская, целиком. Ни одного слова и ни одного знака на других "
        "языках — ответ читается вслух, и чужие буквы превращаются в набор звуков."
    ),
    "en": (
        "Speech: English only, entirely. Not a single word or character in another "
        "language anywhere in the reply — it is read aloud, and foreign letters turn "
        "into noise."
    ),
}


class LanguageError(RuntimeError):
    """Язык не поддержан или ассистент ещё не запущен."""


_runtime: dict[str, Any] = {"transcriber": None, "speaker": None}
_active = DEFAULT


def bind(transcriber: Any, speaker: Any) -> None:
    _runtime.update(transcriber=transcriber, speaker=speaker)


def bound() -> bool:
    return _runtime["transcriber"] is not None and _runtime["speaker"] is not None


def active() -> str:
    return _active


def speech_rule(language: str | None = None) -> str:
    return SPEECH_RULES.get(language or _active, SPEECH_RULES[DEFAULT])


def set_active_quiet(language: str) -> None:
    """Синхронизирует голос с языком, уже сохранённым в config.json — без записи в файл.

    Вызывается один раз при старте: config.json может нести «en» с прошлого раза,
    и голос должен зазвучать на нём сразу, а не только после следующей команды.
    """
    global _active
    if language not in LANGUAGES:
        language = DEFAULT
    _active = language
    if not bound():
        return
    from . import voices

    edge_voice = None
    if voices.bound():
        profile = voices.active()
        edge_voice = profile.edge_voice_en if language == "en" else profile.edge_voice
    _runtime["transcriber"].set_language(language)
    _runtime["speaker"].set_language(language, edge_voice=edge_voice)


def set_active(language: str) -> str:
    """Переключает язык прямо в работающем ассистенте и запоминает выбор в config.json."""
    global _active
    if language not in LANGUAGES:
        raise LanguageError(f"язык «{language}» не поддержан. Есть: {', '.join(NAMES.values())}")

    transcriber = _runtime["transcriber"]
    speaker = _runtime["speaker"]
    if transcriber is None or speaker is None:
        raise LanguageError("ассистент ещё не запущен")

    from . import config, voices

    edge_voice = None
    if voices.bound():
        profile = voices.active()
        edge_voice = profile.edge_voice_en if language == "en" else profile.edge_voice

    transcriber.set_language(language)
    speaker.set_language(language, edge_voice=edge_voice)
    _active = language
    config.save_section("stt", {"language": language})
    return language
