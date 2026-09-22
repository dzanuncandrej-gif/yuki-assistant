"""Палитра и стили. Строгая деловая тёмная тема: графит, тонкие рамки, минимум скруглений."""

from __future__ import annotations

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
MONO: Final = '"Cascadia Mono", "Consolas", monospace'

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
    font-family: "Segoe UI", system-ui, sans-serif;
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
MENU_CARD: Final = (
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
    "stop:0 rgba(20, 28, 46, 0.72), stop:1 rgba(6, 9, 18, 0.72))"
)


MENU_QSS: Final = f"""
#menuRoot {{
    background: {MENU_BG};
}}

/* ---------------------------------------------------------------- боковая навигация */

#menuSidebar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(12, 19, 34, 0.96), stop:1 rgba(5, 8, 16, 0.72));
    border-right: 1px solid rgba(120, 170, 255, 0.10);
}}

#menuBrand {{
    color: {TEXT};
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 9px;
}}

#menuBrandSub {{
    color: {MUTED};
    font-family: {MONO};
    font-size: 9px;
    letter-spacing: 4px;
}}

/* Заголовок группы разделов. Разделов много, и без подписей столбец
   превращается в сплошной список, по которому трудно вести глаз. */
#menuGroup {{
    color: rgba(120, 150, 195, 0.75);
    font-family: {MONO};
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 3px;
    padding: 2px 0 6px 14px;
}}

/* Пункт раздела: слева место под акцентную полосу, она же показывает выбранный.
   Полоса нагляднее подсветки фона — глаз находит текущий раздел, не читая. */
QPushButton#menuTab {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0px;
    color: rgba(190, 205, 228, 0.72);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1.1px;
    padding: 12px 14px 12px 16px;
    margin: 1px 10px 1px 0px;
    text-align: left;
}}
QPushButton#menuTab:hover {{
    background: rgba(120, 170, 255, 0.07);
    border-left-color: rgba(88, 182, 255, 0.45);
    color: {TEXT};
}}
QPushButton#menuTab:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(88, 182, 255, 0.20), stop:1 rgba(88, 182, 255, 0.00));
    border-left-color: {ACCENT};
    color: #ffffff;
}}

/* ---------------------------------------------------------------- шапка раздела */

#menuTitle {{
    color: {TEXT};
    font-size: 24px;
    font-weight: 300;
    letter-spacing: 6px;
}}

#menuSubtitle {{
    color: {MUTED};
    font-family: {MONO};
    font-size: 10px;
    letter-spacing: 2px;
}}

#menuRule {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:0.35 rgba(139, 108, 255, 0.55), stop:1 rgba(88, 182, 255, 0.0));
    border: none;
    max-height: 2px;
    min-height: 2px;
    border-radius: 1px;
}}

#menuBadge {{
    color: {ACCENT};
    font-family: {MONO};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
    border: 1px solid rgba(88, 182, 255, 0.35);
    border-radius: 6px;
    padding: 5px 10px;
    background: rgba(88, 182, 255, 0.08);
}}

/* ---------------------------------------------------------------- карточки */

QFrame#menuCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(24, 33, 54, 0.82), stop:1 rgba(9, 13, 24, 0.82));
    border: 1px solid rgba(120, 170, 255, 0.12);
    border-top: 1px solid rgba(160, 200, 255, 0.16);
    border-radius: 16px;
}}

#cardTitle {{
    color: {TEXT};
    font-size: 12.5px;
    font-weight: 700;
    letter-spacing: 2.5px;
}}

#cardHint {{
    color: rgba(150, 165, 190, 0.85);
    font-size: 11.5px;
}}

/* Тонкая линия между строками: без неё длинный список настроек сливается
   в сплошное полотно и глаз теряет, к какой подписи относится переключатель. */
#menuRow {{
    border-bottom: 1px solid rgba(120, 170, 255, 0.06);
}}
#menuRow[last="true"] {{
    border-bottom: none;
}}

#rowLabel {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 500;
}}

#rowHint {{
    color: rgba(130, 145, 170, 0.9);
    font-size: 11px;
}}

#rowValue {{
    color: {ACCENT};
    font-family: {MONO};
    font-size: 11px;
    font-weight: 600;
    background: rgba(88, 182, 255, 0.10);
    border: 1px solid rgba(88, 182, 255, 0.22);
    border-radius: 6px;
    padding: 3px 0px;
}}

/* ---------------------------------------------------------------- поля ввода */

QComboBox#menuSelect {{
    background: rgba(9, 14, 26, 0.92);
    border: 1px solid rgba(120, 170, 255, 0.18);
    border-radius: 10px;
    padding: 9px 14px;
    min-width: 176px;
    color: {TEXT};
    font-size: 12px;
}}
QComboBox#menuSelect:hover {{ border-color: rgba(88, 182, 255, 0.55); }}
QComboBox#menuSelect:focus {{ border-color: {ACCENT}; }}
QComboBox#menuSelect::drop-down {{
    border: none;
    width: 22px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
/* Каретка рисуется рамками: картинки в теме нет, а без неё список не читался
   как раскрывающийся — люди не понимали, что по нему можно щёлкнуть. */
QComboBox#menuSelect::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid rgba(160, 190, 230, 0.9);
    margin-right: 8px;
}}
QComboBox#menuSelect::down-arrow:hover {{
    border-top-color: {ACCENT};
}}
QComboBox#menuSelect QAbstractItemView {{
    background: {PANEL_SOLID};
    border: 1px solid rgba(88, 182, 255, 0.28);
    border-radius: 10px;
    selection-background-color: rgba(88, 182, 255, 0.22);
    color: {TEXT};
    padding: 6px;
    outline: none;
}}

QLineEdit#menuInput {{
    background: rgba(9, 14, 26, 0.92);
    border: 1px solid rgba(120, 170, 255, 0.18);
    border-radius: 10px;
    padding: 10px 14px;
    color: {TEXT};
    font-size: 12.5px;
    min-width: 200px;
    selection-background-color: {ACCENT};
    selection-color: #04060d;
}}
QLineEdit#menuInput:hover {{ border-color: rgba(88, 182, 255, 0.4); }}
QLineEdit#menuInput:focus {{ border-color: {ACCENT}; }}

QTextEdit {{
    background: rgba(9, 14, 26, 0.92);
    border: 1px solid rgba(120, 170, 255, 0.18);
    border-radius: 12px;
    padding: 10px 12px;
    color: {TEXT};
    font-size: 12.5px;
    selection-background-color: {ACCENT};
    selection-color: #04060d;
}}
QTextEdit:focus {{ border-color: {ACCENT}; }}

/* ---------------------------------------------------------------- ползунок */

QSlider#menuSlider::groove:horizontal {{
    height: 4px;
    background: rgba(120, 170, 255, 0.14);
    border-radius: 2px;
}}
QSlider#menuSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(88, 182, 255, 0.45), stop:1 {ACCENT});
    border-radius: 2px;
}}
QSlider#menuSlider::handle:horizontal {{
    background: #eaf4ff;
    border: 2px solid {ACCENT};
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider#menuSlider::handle:horizontal:hover {{
    background: {ACCENT};
    border-color: #eaf4ff;
}}

/* ---------------------------------------------------------------- кнопки */

QPushButton#menuAction {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(88, 182, 255, 0.22), stop:1 rgba(139, 108, 255, 0.18));
    border: 1px solid rgba(88, 182, 255, 0.42);
    border-radius: 10px;
    color: #eaf4ff;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 1.4px;
    padding: 10px 20px;
}}
QPushButton#menuAction:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(88, 182, 255, 0.38), stop:1 rgba(139, 108, 255, 0.30));
    border-color: {ACCENT};
}}
QPushButton#menuAction:pressed {{
    background: rgba(88, 182, 255, 0.45);
}}

QPushButton#menuGhost {{
    background: rgba(120, 170, 255, 0.04);
    border: 1px solid rgba(120, 170, 255, 0.16);
    border-radius: 10px;
    color: rgba(190, 205, 228, 0.85);
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 1.2px;
    padding: 10px 18px;
}}
QPushButton#menuGhost:hover {{
    color: {TEXT};
    background: rgba(120, 170, 255, 0.10);
    border-color: rgba(88, 182, 255, 0.45);
}}

/* Недоступная кнопка обязана выглядеть недоступной. Без этого «Отправить»
   светилась ровно так же, как рабочая, — человек жал её и не понимал, почему
   ничего не происходит. А в разделе сообщений именно эта кнопка заблокирована
   до тех пор, пока адресат не подтверждён. */
QPushButton#menuAction:disabled, QPushButton#menuGhost:disabled {{
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.22);
}}

/* Кнопка закрытия в шапке: крестик рисуется шрифтом, поэтому размер задаётся
   явно — иначе на части систем глиф не находился и оставался пустой квадрат. */
QPushButton#menuClose {{
    background: transparent;
    border: 1px solid rgba(120, 170, 255, 0.14);
    border-radius: 8px;
    color: rgba(190, 205, 228, 0.8);
    font-family: {MONO};
    font-size: 15px;
    font-weight: 600;
    padding: 0px;
}}
QPushButton#menuClose:hover {{
    background: rgba(224, 92, 92, 0.18);
    border-color: rgba(224, 92, 92, 0.5);
    color: #ffdede;
}}

QScrollArea#menuScroll {{ background: transparent; border: none; }}
QScrollArea#menuScroll > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(120, 170, 255, 0.22);
    border-radius: 4px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(88, 182, 255, 0.45); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""
