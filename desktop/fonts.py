"""Шрифты интерфейса — те же, что на сайте проекта.

Unbounded для заголовков, Inter Tight для текста, JetBrains Mono для служебных
подписей. Qt не читает woff2, поэтому в `assets/fonts` лежат статические TTF,
собранные из них (лицензия SIL OFL — `assets/fonts/OFL.txt`). Нет файлов —
интерфейс спокойно работает на системных шрифтах.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

DISPLAY = "Yuki Display"
SANS = "Yuki Sans"
MONO = "Yuki Mono"

_FOLDER = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_loaded: set[str] = set()


def load() -> set[str]:
    """Регистрирует шрифты в приложении. Вызывать после создания QApplication."""
    if _loaded:
        return _loaded
    for path in sorted(_FOLDER.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            _loaded.update(QFontDatabase.applicationFontFamilies(font_id))
    return _loaded


def font(family: str, size: float, weight: QFont.Weight = QFont.Weight.Normal,
         spacing: float = 0.0) -> QFont:
    """Шрифт с запасным вариантом: если своего семейства нет — системный."""
    chosen = QFont(family if family in _loaded else "Segoe UI")
    chosen.setPointSizeF(size)
    chosen.setWeight(weight)
    if spacing:
        chosen.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    chosen.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return chosen
