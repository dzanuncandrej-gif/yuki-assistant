"""Быстрые команды без модели: какой шаблон ловит какую фразу.

Разбор здесь важнее, чем кажется: если шаблон не совпал, просьба уходит в
языковую модель, и «выключи музыку» может обернуться запуском музыки.
"""

from __future__ import annotations

import pytest

from core import commands

MEDIA_CASES = [
    ("выключи музыку", "media_stop"),
    ("следующая музыка", "media_next"),
    ("следующий трек", "media_next"),
    ("дальше", "media_next"),
    ("включи другую песню", "media_next"),
    ("найди видео котов", "video"),
    ("включи видео про котиков", "video"),
]

SYSTEM_CASES = [
    ("громкость 30", "volume_set"),
    ("сделай скриншот", "screenshot"),
    ("который час", "time"),
    ("сверни всё", "minimize_all"),
    ("выключи компьютер", "power_off"),
    ("что ты умеешь", "help"),
]


@pytest.mark.parametrize(("phrase", "intent"), MEDIA_CASES + SYSTEM_CASES)
def test_phrase_matches_expected_intent(phrase: str, intent: str) -> None:
    assert commands.match_intent(phrase) == intent


def test_language_switch_is_recognised() -> None:
    for phrase in ("говори по-английски", "switch to english", "говори по-русски"):
        assert commands.match_intent(phrase) == "language_set"


def test_small_talk_is_left_to_the_model() -> None:
    """Разговорные фразы не должны попадать в быстрые команды."""
    for phrase in ("как дела", "что нового у тебя", "расскажи анекдот"):
        assert commands.match_intent(phrase) != "open"


def test_every_intent_has_an_example() -> None:
    for intent in commands.catalog():
        assert intent.example.strip(), f"у шаблона {intent.name} нет примера для справки"


def test_intent_names_are_unique() -> None:
    names = [intent.name for intent in commands.catalog()]
    assert len(names) == len(set(names))
