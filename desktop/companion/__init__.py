"""Экранный компаньон: живой аниме-персонаж, её анимация, панель и голос.

Пакет собран из независимых слоёв, чтобы позже к нему можно было подключить
любые «умные» возможности, не переписывая рисование:

    skin.py      — палитра и пропорции персонажа (внешность без логики)
    rig.py       — поза и отрисовка: чистая функция «поза → кадр»
    emotions.py  — набор эмоций: во что превращается каждая поза
    animator.py  — жизнь: дыхание, моргание, взгляд, липсинк, физика волос
    widget.py    — виджет Qt, который крутит анимацию 60 кадров в секунду
    panel.py     — окно на рабочем столе: персонаж, реплики, быстрые кнопки
    voice.py     — голосовой слой компаньона поверх core.tts
"""

from __future__ import annotations

from .animator import Animator
from .emotions import EMOTIONS, Emotion, emotion_for
from .panel import CompanionPanel
from .rig import Pose, draw_character
from .skin import DEFAULT_SKIN, Skin
from .widget import CharacterWidget

__all__ = [
    "Animator",
    "CharacterWidget",
    "CompanionPanel",
    "DEFAULT_SKIN",
    "EMOTIONS",
    "Emotion",
    "Pose",
    "Skin",
    "draw_character",
    "emotion_for",
]
