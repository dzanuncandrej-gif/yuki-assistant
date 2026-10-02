"""Палитра и стили. Строгая деловая тёмная тема: графит, тонкие рамки, минимум скруглений."""

from __future__ import annotations

from pathlib import Path
from typing import Final

BG: Final = "#020306"
GLASS: Final = (
    "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    "stop:0 rgba(18, 24, 38, 0.78), stop:1 rgba(4, 6, 12, 0.72))"
)
GLASS_HOT: Final = (
    "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    "stop:0 rgba(26, 44, 74, 0.85), stop:1 rgba(8, 14, 26, 0.80))"
)
PANEL: Final = "rgba(3, 5, 11, 0.86)"
PANEL_SOLID: Final = "#03050b"
BORDER: Final = "rgba(120, 170, 255, 0.09)"
BORDER_STRONG: Final = "rgba(120, 180, 255, 0.22)"
TEXT: Final = "#dfe8f7"
MUTED: Final = "#55637a"
ACCENT: Final = "#58b6ff"
ACCENT_SOFT: Final = "rgba(88, 182, 255, 0.16)"
VIOLET: Final = "#8b6cff"
DANGER: Final = "#ff6b6b"
MONO: Final = '"Yuki Mono", "Cascadia Mono", "Consolas", monospace'
SANS: Final = '"Yuki Sans", "Segoe UI", system-ui, sans-serif'
DISPLAY: Final = '"Yuki Display", "Segoe UI", sans-serif'

STATE_COLORS: Final = {
    "idle": "#7fb2ff",
    "listening": "#69e2ff",
    "thinking": "#a88cff",
    "speaking": "#8fd8ff",
    "offline": "#ff7a94",
}

STATE_LABELS: Final = {
    "idle": "ОЖИДАНИЕ",
    "listening": "ПРИЁМ",
    "thinking": "ОБРАБОТКА",
    "speaking": "ОТВЕТ",
}

KIND_COLORS: Final = {
    "user": "#7cc4ff",
    "assistant": "#ffc078",
    "system": MUTED,
    "error": "#ff8080",
}

KIND_LABELS: Final = {
    "user": "оператор",
    "assistant": "юки",
    "system": "система",
    "error": "ошибка",
}

AUTHOR: Final = "@cruror"

# Параметры орба по состояниям: цвет ядра, цвет ореола, амплитуда, скорость, масштаб шума, свечение.
# Холодная гамма во всех состояниях: окно управления не должно спорить с
# персонажем на рабочем столе. Состояния различаются яркостью и подвижностью,
# а не цветом в другой части спектра.
ORB_PRESETS: Final = {
    "idle": ((0.05, 0.18, 0.46), (0.32, 0.66, 1.00), 0.018, 0.22, 1.5, 0.42),
    "listening": ((0.05, 0.44, 0.72), (0.46, 0.92, 1.00), 0.034, 0.55, 1.9, 0.78),
    "thinking": ((0.24, 0.20, 0.72), (0.66, 0.62, 1.00), 0.052, 1.35, 2.4, 0.88),
    "speaking": ((0.10, 0.42, 0.84), (0.72, 0.90, 1.00), 0.044, 0.80, 1.8, 0.92),
}

QSS: Final = f"""
QWidget {{
    color: {TEXT};
    font-family: {SANS};
    font-size: 13px;
}}

#root {{
    background: {BG};
}}

#titleBar, #footer {{
    background: transparent;
}}

#brand {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 7px;
}}

#brandSub {{
    color: {MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 3px;
}}

#rule {{
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

#statusPill {{
    background: {GLASS};
    border: 1px solid {BORDER_STRONG};
    border-radius: 3px;
}}

#statusText {{
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 2px;
    color: {TEXT};
}}

QPushButton#chrome {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    color: {MUTED};
    font-size: 14px;
    padding: 0;
}}
QPushButton#chrome:hover {{
    background: rgba(120, 150, 195, 0.12);
    border-color: {BORDER_STRONG};
    color: {TEXT};
}}
QPushButton#chrome[danger="true"]:hover {{
    background: rgba(224, 92, 92, 0.20);
    border-color: rgba(224, 92, 92, 0.45);
    color: #ffdede;
}}

#logScroll {{
    background: transparent;
    border: none;
}}
#logScroll QWidget {{
    background: transparent;
}}

QFrame#card {{
    background: {GLASS};
    border: 1px solid {BORDER};
    border-left: 2px solid {BORDER_STRONG};
    border-radius: 5px;
}}
QFrame#card[kind="user"] {{
    border-left-color: {KIND_COLORS["user"]};
}}
QFrame#card[kind="assistant"] {{
    border-left-color: {KIND_COLORS["assistant"]};
}}
QFrame#card[kind="error"] {{
    border-left-color: {KIND_COLORS["error"]};
}}

QLabel[role="who"] {{
    font-family: {MONO};
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 2px;
}}

QLabel[role="body"] {{
    font-size: 13.5px;
    color: {TEXT};
}}

QLineEdit {{
    background: {GLASS};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 12px 16px;
    letter-spacing: 0.3px;
    selection-background-color: {ACCENT};
    selection-color: #04060d;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

QPushButton#action {{
    background: {GLASS};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 12px 20px;
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 1.4px;
}}
QPushButton#action:hover {{
    background: rgba(78, 168, 255, 0.20);
    border-color: {ACCENT};
}}
QPushButton#action:checked {{
    background: rgba(224, 92, 92, 0.18);
    border-color: rgba(224, 92, 92, 0.5);
}}

QComboBox#voiceBox {{
    background: {GLASS};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 6px 10px;
    min-width: 132px;
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 2px;
    color: {TEXT};
}}
QComboBox#voiceBox:hover {{
    border-color: {ACCENT};
}}
/* стрелку рисует не Qt, а отдельная подпись рядом: так она совпадает с остальной типографикой */
QComboBox#voiceBox::drop-down {{
    border: none;
    width: 0;
}}
QComboBox#voiceBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border: none;
}}
QComboBox#voiceBox QAbstractItemView {{
    background: {PANEL_SOLID};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: rgba(78, 168, 255, 0.18);
    color: {TEXT};
    padding: 4px;
    outline: none;
}}

#hint {{
    color: {MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 1px;
}}

#author {{
    color: {MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 1px;
    padding: 3px 8px;
    border: 1px solid transparent;
    border-radius: 3px;
}}
#author:hover {{
    color: {TEXT};
    border-color: {BORDER_STRONG};
    background: {PANEL};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 2px 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(120, 150, 195, 0.30);
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(120, 150, 195, 0.55);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QToolTip {{
    background: {PANEL_SOLID};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 5px 8px;
}}

QMenu {{
    background: {PANEL_SOLID};
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    padding: 5px;
}}
QMenu::item {{
    padding: 7px 24px 7px 14px;
    border-radius: 3px;
    font-size: 12px;
}}
QMenu::item:selected {{
    background: rgba(78, 168, 255, 0.16);
}}
"""

# ---------------------------------------------------------------- режим видеосвязи

CALL_QSS: Final = f"""
#callRoot {{
    background: qradialgradient(cx:0.5, cy:0.35, radius:1.1,
        stop:0 rgba(10, 18, 34, 1.0), stop:0.55 rgba(4, 7, 14, 1.0), stop:1 {BG});
}}

#holoPanel {{
    background: {GLASS};
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
}}

#holoTitle {{
    color: {ACCENT};
    font-family: {MONO};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 3px;
}}

#holoMetric {{
    color: {TEXT};
    font-family: {MONO};
    font-size: 11px;
    line-height: 150%;
    letter-spacing: 0.5px;
}}

#holoShot {{
    background: rgba(0, 0, 0, 0.45);
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {MUTED};
    font-family: {MONO};
    font-size: 10px;
}}

#holoLive {{
    color: #ff7b7b;
    font-family: {MONO};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
}}

#holoState {{
    color: {ACCENT};
    font-family: {MONO};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 8px;
}}

#holoCaption {{
    color: {TEXT};
    font-size: 16px;
    line-height: 145%;
    padding: 0 30px;
}}

QPushButton#callButton, QPushButton#callDanger {{
    background: {GLASS};
    border: 1px solid {BORDER_STRONG};
    border-radius: 22px;
    padding: 12px 26px;
    font-family: {MONO};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 2px;
    color: {TEXT};
}}
QPushButton#callButton:hover {{
    background: {GLASS_HOT};
    border-color: {ACCENT};
}}
QPushButton#callButton:checked {{
    background: rgba(255, 107, 107, 0.18);
    border-color: rgba(255, 107, 107, 0.55);
}}
QPushButton#callDanger {{
    border-color: rgba(255, 107, 107, 0.45);
    color: #ffd9d9;
}}
QPushButton#callDanger:hover {{
    background: rgba(255, 107, 107, 0.22);
    border-color: {DANGER};
}}
"""

# ---------------------------------------------------------------- панель компаньона

COMPANION_QSS: Final = f"""
#companionRoot {{
    background: transparent;
}}

#companionDock {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(16, 24, 40, 0.88), stop:1 rgba(4, 7, 14, 0.92));
    border: 1px solid {BORDER_STRONG};
    border-radius: 22px;
}}

#companionState {{
    font-family: {MONO};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}}

#companionHint {{
    color: {MUTED};
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 1px;
}}

QPushButton#companionButton, QPushButton#companionDanger {{
    background: rgba(120, 170, 255, 0.07);
    border: 1px solid {BORDER};
    border-radius: 14px;
    color: {TEXT};
    font-size: 12px;
}}
QPushButton#companionButton:hover {{
    background: rgba(88, 182, 255, 0.20);
    border-color: {ACCENT};
}}
QPushButton#companionDanger:hover {{
    background: rgba(224, 92, 92, 0.22);
    border-color: rgba(224, 92, 92, 0.5);
    color: #ffe0e0;
}}
"""

# ---------------------------------------------------------------- меню управления

MENU_BG: Final = "#04060c"
# стрелка списков — картинкой: треугольник из рамок в Qt рисовался полоской
CHEVRON: Final = (Path(__file__).resolve().parent.parent / "assets" / "ui" / "chevron-down.svg").as_posix()
MENU_CARD: Final = (
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
    "stop:0 rgba(20, 28, 46, 0.72), stop:1 rgba(6, 9, 18, 0.72))"
)


MENU_QSS: Final = f"""
#menuRoot {{
    background: {MENU_BG};
    font-family: {SANS};
}}

/* ---------------------------------------------------------------- боковая навигация */

#menuSidebar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(10, 16, 34, 0.94), stop:0.6 rgba(6, 10, 22, 0.90), stop:1 rgba(12, 9, 30, 0.94));
    border-right: 1px solid rgba(130, 170, 255, 0.12);
}}

#menuGroup {{
    color: rgba(125, 150, 200, 0.78);
    font-family: {MONO};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 3px;
    padding: 6px 0 4px 16px;
}}

#menuHint {{
    color: rgba(125, 140, 170, 0.8);
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 1px;
}}

/* ---------------------------------------------------------------- шапка раздела */

#menuTitle {{
    color: #ffffff;
    font-family: {DISPLAY};
    font-size: 25px;
    font-weight: 700;
}}

#menuSubtitle {{
    color: rgba(170, 185, 212, 0.92);
    font-family: {SANS};
    font-size: 13px;
}}

#menuRule {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(88, 182, 255, 0.85), stop:0.3 rgba(139, 108, 255, 0.45), stop:1 rgba(88, 182, 255, 0.0));
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ---------------------------------------------------------------- карточки */

QFrame#menuCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(26, 38, 72, 0.78), stop:0.55 rgba(12, 18, 36, 0.80), stop:1 rgba(18, 12, 40, 0.82));
    border: 1px solid rgba(130, 170, 255, 0.14);
    border-top: 1px solid rgba(150, 200, 255, 0.30);
    border-radius: 20px;
}}
QFrame#menuCard:hover {{
    border: 1px solid rgba(110, 170, 255, 0.28);
    border-top: 1px solid rgba(150, 210, 255, 0.45);
}}

#cardTitle {{
    color: #ffffff;
    font-family: {DISPLAY};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding-bottom: 2px;
}}

#cardHint {{
    color: rgba(165, 180, 208, 0.9);
    font-size: 12.5px;
}}

#menuRow {{
    border-bottom: 1px solid rgba(130, 170, 255, 0.08);
}}
#menuRow[last="true"] {{
    border-bottom: none;
}}

#rowLabel {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 600;
}}

#rowHint {{
    color: rgba(140, 155, 182, 0.95);
    font-size: 12px;
}}

#rowValue {{
    color: #ffffff;
    font-family: {MONO};
    font-size: 11px;
    font-weight: 700;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(88, 182, 255, 0.28), stop:1 rgba(139, 108, 255, 0.28));
    border: 1px solid rgba(120, 190, 255, 0.40);
    border-radius: 8px;
    padding: 4px 0px;
}}

/* ---------------------------------------------------------------- поля ввода */

QComboBox#menuSelect {{
    background: rgba(8, 13, 28, 0.92);
    border: 1px solid rgba(130, 170, 255, 0.22);
    border-radius: 12px;
    padding: 10px 16px;
    min-width: 190px;
    color: {TEXT};
    font-size: 13px;
    font-weight: 600;
}}
QComboBox#menuSelect:hover {{ border-color: rgba(88, 182, 255, 0.60); background: rgba(14, 22, 44, 0.95); }}
QComboBox#menuSelect:focus {{ border-color: {ACCENT}; }}
QComboBox#menuSelect::drop-down {{
    border: none;
    width: 26px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox#menuSelect::down-arrow {{
    image: url({CHEVRON});
    width: 14px;
    height: 14px;
    margin-right: 12px;
}}
QComboBox#menuSelect QAbstractItemView {{
    background: #070b18;
    border: 1px solid rgba(88, 182, 255, 0.35);
    border-radius: 12px;
    selection-background-color: rgba(88, 140, 255, 0.30);
    selection-color: #ffffff;
    color: {TEXT};
    padding: 6px;
    outline: none;
}}

QLineEdit#menuInput {{
    background: rgba(8, 13, 28, 0.92);
    border: 1px solid rgba(130, 170, 255, 0.22);
    border-radius: 12px;
    padding: 11px 16px;
    color: {TEXT};
    font-size: 13px;
    min-width: 220px;
    selection-background-color: {ACCENT};
    selection-color: #04060d;
}}
QLineEdit#menuInput:hover {{ border-color: rgba(88, 182, 255, 0.50); }}
QLineEdit#menuInput:focus {{ border-color: {ACCENT}; background: rgba(12, 20, 42, 0.95); }}

QTextEdit {{
    background: rgba(8, 13, 28, 0.92);
    border: 1px solid rgba(130, 170, 255, 0.22);
    border-radius: 14px;
    padding: 12px 14px;
    color: {TEXT};
    font-size: 13px;
    selection-background-color: {ACCENT};
    selection-color: #04060d;
}}
QTextEdit:focus {{ border-color: {ACCENT}; }}

/* ---------------------------------------------------------------- ползунок */

QSlider#menuSlider::groove:horizontal {{
    height: 6px;
    background: rgba(130, 170, 255, 0.14);
    border-radius: 3px;
}}
QSlider#menuSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {VIOLET});
    border-radius: 3px;
}}
QSlider#menuSlider::handle:horizontal {{
    background: #ffffff;
    border: 3px solid {ACCENT};
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 9px;
}}
QSlider#menuSlider::handle:horizontal:hover {{
    border-color: {VIOLET};
}}

/* ---------------------------------------------------------------- кнопки */

QPushButton#menuAction {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7cc7ff, stop:1 #a48dff);
    border: none;
    border-radius: 12px;
    color: #041022;
    font-size: 12.5px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding: 11px 22px;
}}
QPushButton#menuAction:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #98d4ff, stop:1 #b8a6ff);
}}
QPushButton#menuAction:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5fb0f0, stop:1 #8c73f0);
}}

QPushButton#menuGhost {{
    background: rgba(14, 22, 44, 0.70);
    border: 1px solid rgba(130, 170, 255, 0.24);
    border-radius: 12px;
    color: {TEXT};
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.3px;
    padding: 11px 20px;
}}
QPushButton#menuGhost:hover {{
    background: rgba(26, 40, 80, 0.80);
    border-color: rgba(88, 182, 255, 0.60);
    color: #ffffff;
}}

QPushButton#menuRemove {{
    background: rgba(14, 22, 44, 0.55);
    border: 1px solid rgba(130, 170, 255, 0.18);
    border-radius: 10px;
    color: rgba(185, 196, 216, 0.9);
    font-size: 16px;
    font-weight: 600;
    padding: 0px;
}}
QPushButton#menuRemove:hover {{
    background: rgba(255, 90, 120, 0.22);
    border-color: rgba(255, 107, 133, 0.6);
    color: #ffffff;
}}

QPushButton#menuAction:disabled, QPushButton#menuGhost:disabled {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.07);
    color: rgba(255, 255, 255, 0.25);
}}

QScrollArea#menuScroll {{ background: transparent; border: none; }}
QScrollArea#menuScroll > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(130, 170, 255, 0.22);
    border-radius: 5px;
    min-height: 44px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(88, 182, 255, 0.50); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QToolTip {{
    background: #0a1022;
    color: {TEXT};
    border: 1px solid rgba(88, 182, 255, 0.40);
    border-radius: 8px;
    padding: 6px 10px;
}}
"""
