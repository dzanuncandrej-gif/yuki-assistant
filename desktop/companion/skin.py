"""Внешность персонажа: цвета и пропорции. Ни одной строчки логики.

Скин отделён от рисования намеренно: чтобы поменять героиню (другой цвет волос,
глаз, костюма), достаточно собрать новый Skin — код анимации и панели не меняется.
Значения взяты с референса: пепельно-русые волосы, зелёные глаза, чёрно-бирюзовый
костюм с золотой фурнитурой и кошачьи уши.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Final

from PySide6.QtGui import QColor


def _c(value: str) -> QColor:
    return QColor(value)


@dataclass(frozen=True)
class Skin:
    """Палитра персонажа. Все цвета — QColor, чтобы не разбирать строки на каждом кадре."""

    name: str = "Мира"

    # кожа
    skin: QColor = field(default_factory=lambda: _c("#f8e4d6"))
    skin_shade: QColor = field(default_factory=lambda: _c("#eac6b4"))
    skin_deep: QColor = field(default_factory=lambda: _c("#d6a292"))
    blush: QColor = field(default_factory=lambda: _c("#f0908f"))

    # волосы
    hair: QColor = field(default_factory=lambda: _c("#cfc2a4"))
    hair_light: QColor = field(default_factory=lambda: _c("#efe6cd"))
    hair_dark: QColor = field(default_factory=lambda: _c("#8f8266"))
    hair_shine: QColor = field(default_factory=lambda: _c("#fdf8e8"))

    # глаза
    iris: QColor = field(default_factory=lambda: _c("#7fbf6a"))
    iris_deep: QColor = field(default_factory=lambda: _c("#33623a"))
    iris_glow: QColor = field(default_factory=lambda: _c("#c9f39a"))
    pupil: QColor = field(default_factory=lambda: _c("#16200f"))
    sclera: QColor = field(default_factory=lambda: _c("#fbfdff"))
    lash: QColor = field(default_factory=lambda: _c("#2a2620"))
    brow: QColor = field(default_factory=lambda: _c("#9a8b6a"))

    # костюм
    cloth_dark: QColor = field(default_factory=lambda: _c("#171b26"))
    cloth_dark_2: QColor = field(default_factory=lambda: _c("#0b0e16"))
    cloth_teal: QColor = field(default_factory=lambda: _c("#2fa5c4"))
    cloth_teal_deep: QColor = field(default_factory=lambda: _c("#166a8c"))
    cloth_gauze: QColor = field(default_factory=lambda: _c("#e9d9a2"))
    gold: QColor = field(default_factory=lambda: _c("#e0b95c"))
    gold_deep: QColor = field(default_factory=lambda: _c("#9a7526"))
    white: QColor = field(default_factory=lambda: _c("#f4f7fb"))

    # уши и мех
    ear_outer: QColor = field(default_factory=lambda: _c("#3a3226"))
    ear_inner: QColor = field(default_factory=lambda: _c("#3f8fc4"))

    # свечение вокруг фигуры (совпадает с состоянием ассистента)
    aura: QColor = field(default_factory=lambda: _c("#58b6ff"))
    line: QColor = field(default_factory=lambda: _c("#3a3226"))

    def with_aura(self, color: QColor) -> Skin:
        """Свечение меняется вместе с состоянием — остальная внешность нет."""
        return replace(self, aura=QColor(color))


DEFAULT_SKIN: Final = Skin()

# альтернативные варианты внешности — меню выбирает их по ключу
VARIANTS: Final[dict[str, Skin]] = {
    "mira": DEFAULT_SKIN,
    "yuki": replace(
        DEFAULT_SKIN,
        name="Юки",
        hair=_c("#e7dcc6"),
        hair_light=_c("#fbf6ea"),
        hair_dark=_c("#a89a7c"),
        iris=_c("#6fc6d8"),
        iris_deep=_c("#2b5f75"),
        iris_glow=_c("#c7f2ff"),
        cloth_teal=_c("#59c3d8"),
        cloth_teal_deep=_c("#1f7c9c"),
        ear_inner=_c("#65b6e0"),
    ),
    "sora": replace(
        DEFAULT_SKIN,
        name="Сора",
        hair=_c("#c3b4a2"),
        hair_light=_c("#e6dccd"),
        hair_dark=_c("#7f7261"),
        iris=_c("#b083e0"),
        iris_deep=_c("#4c2f75"),
        iris_glow=_c("#e6ccff"),
        cloth_teal=_c("#7e7ad4"),
        cloth_teal_deep=_c("#3c3a86"),
        ear_inner=_c("#8f86e0"),
    ),
}


def variant(key: str) -> Skin:
    return VARIANTS.get(key, DEFAULT_SKIN)
