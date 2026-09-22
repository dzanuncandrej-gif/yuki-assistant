"""Панель компаньона: окно с живым персонажем прямо на рабочем столе.

Окно без рамки и без фона. Видны только фигура, свет под ней, облако реплики и
стеклянная панель управления, которая проявляется при наведении. Панель не
забирает фокус у других программ — ею можно пользоваться, не прерывая работу.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import COMPANION_QSS, STATE_COLORS, STATE_LABELS
from .emotions import EMOTIONS
from .live import make_character

PANEL_W = 360
PANEL_H = 740
BUBBLE_LIFETIME_MS = 7000
DOCK_IDLE_MS = 3600


def _accent(state: str) -> QColor:
    return QColor(STATE_COLORS.get(state, STATE_COLORS["idle"]))


class Stage(QWidget):
    """Сцена под персонажем: свет, кольца, пылинки.

    Рисуется под фигурой и связывает её с интерфейсом Юки: цвет повторяет
    состояние ассистента, кольца дышат вместе с голосом.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._phase = 0.0
        self._level = 0.0
        self._minimal = False
        self._accent = _accent("idle")
        self._target = QColor(self._accent)
        self._motes = [
            (random.random(), random.random(), random.uniform(0.4, 1.4), random.uniform(0.5, 1.6))
            for _ in range(26)
        ]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str) -> None:
        self._target = _accent(state)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def set_minimal(self, minimal: bool) -> None:
        """Скупой режим: сцена не рисует ничего.

        Под трёхмерным персонажем фон не нужен вовсе — на рабочем столе должна
        остаться только фигура. Свой ореол и пыль сцена three.js рисует сама.
        """
        self._minimal = bool(minimal)
        self._timer.stop() if minimal else self._timer.start(33)
        self.update()

    def _tick(self) -> None:
        self._phase += 0.033
        # цвет перетекает, а не переключается — смена состояния читается мягко
        self._accent = QColor(
            int(self._accent.red() + (self._target.red() - self._accent.red()) * 0.06),
            int(self._accent.green() + (self._target.green() - self._accent.green()) * 0.06),
            int(self._accent.blue() + (self._target.blue() - self._accent.blue()) * 0.06),
        )
        self.update()

    def paintEvent(self, event) -> None:
        if self._minimal:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        accent = self._accent
        pulse = 0.5 + 0.5 * math.sin(self._phase * 1.4)
        energy = 0.25 + 0.75 * self._level

        painter.setPen(Qt.PenStyle.NoPen)
        if not self._minimal:
            # ореол за фигурой
            halo = QRadialGradient(width / 2, height * 0.46, width * 0.62)
            halo.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), int(38 * energy + 12)))
            halo.setColorAt(0.55, QColor(accent.red(), accent.green(), accent.blue(), int(14 * energy + 4)))
            halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setBrush(halo)
            painter.drawEllipse(QRectF(0, height * 0.05, width, height * 0.85))

        # площадка под ногами: заливка и два кольца телеметрии
        base_y = height - 26
        floor = QRadialGradient(width / 2, base_y, width * 0.42)
        floor.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), int(90 * energy + 30)))
        floor.setColorAt(0.7, QColor(accent.red(), accent.green(), accent.blue(), 22))
        floor.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setBrush(floor)
        painter.drawEllipse(QRectF(width * 0.08, base_y - 30, width * 0.84, 60))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, radius in enumerate((0.30, 0.38, 0.46)):
            span = width * radius * (1.0 + 0.02 * pulse * (index + 1))
            alpha = int((70 - index * 18) * (0.5 + 0.5 * energy))
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha), 1.2))
            painter.drawEllipse(QRectF(width / 2 - span, base_y - span * 0.26, span * 2, span * 0.52))

        # редкие пылинки поднимаются вверх — воздух вокруг фигуры живой
        for x, y, size, speed in (() if self._minimal else self._motes):
            position_y = height - ((y * height + self._phase * speed * 26) % height)
            fade = max(0.0, 1.0 - position_y / height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), int(120 * fade * energy)))
            painter.drawEllipse(QRectF(x * width, position_y, size * 2.0, size * 2.0))
        painter.end()


class SpeechBubble(QWidget):
    """Облако реплики над персонажем: стекло, акцентная полоса, мягкое появление."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._shown = ""
        self._accent = _accent("speaking")
        self._font = QFont("Segoe UI", 10)
        self.hide()

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(260)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)

        # текст набирается по буквам: реплика читается как живая речь
        self._typing = QTimer(self)
        self._typing.timeout.connect(self._type)

    def show_text(self, text: str, accent: QColor | None = None) -> None:
        clean = " ".join(text.split())
        if not clean:
            return
        if len(clean) > 240:
            clean = clean[:237] + "…"
        self._text = clean
        self._shown = ""
        if accent is not None:
            self._accent = QColor(accent)
        self._relayout()
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._typing.start(14)
        self._hide_timer.start(BUBBLE_LIFETIME_MS)

    def dismiss(self) -> None:
        self._typing.stop()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()
        QTimer.singleShot(280, self.hide)

    def _type(self) -> None:
        if len(self._shown) >= len(self._text):
            self._typing.stop()
            return
        step = 2 if len(self._text) > 90 else 1
        self._shown = self._text[: len(self._shown) + step]
        self.update()

    def _relayout(self) -> None:
        parent = self.parentWidget()
        width = (parent.width() if parent else PANEL_W) - 34
        metrics = QFontMetrics(self._font)
        rect = metrics.boundingRect(0, 0, width - 44, 4000, int(Qt.TextFlag.TextWordWrap), self._text)
        height = min(184, rect.height() + 36)
        self.setGeometry(17, 10, width, height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(0, 0, self.width(), self.height() - 11)

        path = QPainterPath()
        path.addRoundedRect(body, 16, 16)
        tail = QPainterPath()
        tail.moveTo(body.center().x() - 13, body.bottom() - 1)
        tail.lineTo(body.center().x() + 1, body.bottom() + 11)
        tail.lineTo(body.center().x() + 14, body.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)

        glass = QLinearGradient(body.topLeft(), body.bottomRight())
        glass.setColorAt(0.0, QColor(16, 24, 40, 232))
        glass.setColorAt(1.0, QColor(5, 8, 15, 226))
        painter.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 110), 1.2))
        painter.setBrush(glass)
        painter.drawPath(path)

        # акцентная полоса слева — та же деталь, что у карточек журнала
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 210))
        painter.drawRoundedRect(QRectF(11, 13, 2.6, body.height() - 26), 1.3, 1.3)

        painter.setPen(QColor(226, 235, 248))
        painter.setFont(self._font)
        painter.drawText(
            body.adjusted(22, 12, -14, -10),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            self._shown or self._text,
        )
        painter.end()


class StatusCapsule(QWidget):
    """Капсула состояния над персонажем: имя, режим и живая полоска голоса."""

    def __init__(self, name: str = "Мира", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(30)
        self._name = name
        self._state = "idle"
        self._accent = _accent("idle")
        self._level = 0.0
        self._bars = [random.random() for _ in range(14)]
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_name(self, name: str) -> None:
        self._name = name
        self.update()

    def set_state(self, state: str) -> None:
        self._state = state
        self._accent = _accent(state)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def _tick(self) -> None:
        self._phase += 0.12
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(0, 0, self.width(), self.height())

        glass = QLinearGradient(body.topLeft(), body.bottomLeft())
        glass.setColorAt(0.0, QColor(14, 20, 34, 210))
        glass.setColorAt(1.0, QColor(4, 7, 14, 205))
        painter.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 90), 1.0))
        painter.setBrush(glass)
        painter.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), 15, 15)

        # маркер состояния
        painter.setPen(Qt.PenStyle.NoPen)
        glow = QColor(self._accent)
        glow.setAlpha(int(120 + 100 * (0.5 + 0.5 * math.sin(self._phase))))
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(12, self.height() / 2 - 3.5, 7, 7))

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.setPen(QColor(223, 232, 247))
        painter.drawText(QRectF(26, 0, 110, self.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._name)

        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor(self._accent))
        painter.drawText(QRectF(26, 0, self.width() - 120, self.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                         STATE_LABELS.get(self._state, self._state.upper()))

        # эквалайзер справа
        left = self.width() - 84
        for index in range(len(self._bars)):
            wave = 0.5 + 0.5 * math.sin(self._phase * (1.0 + self._bars[index]) + index * 0.5)
            height = 3 + 12 * wave * (0.16 + 0.84 * self._level)
            color = QColor(self._accent)
            color.setAlphaF(0.25 + 0.55 * self._level)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(
                QRectF(left + index * 4.6, self.height() / 2 - height / 2, 2.2, height), 1.1, 1.1
            )
        painter.end()


class Dock(QWidget):
    """Стеклянная панель управления под персонажем."""

    mic_clicked = Signal()
    call_clicked = Signal()
    menu_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("companionDock")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(44)

        def button(glyph: str, tip: str, name: str = "companionButton") -> QPushButton:
            item = QPushButton(glyph)
            item.setObjectName(name)
            item.setToolTip(tip)
            item.setFixedSize(30, 28)
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            return item

        self.mic = button("🎙", "Микрофон")
        self.call = button("◉", "Видеосвязь")
        self.menu = button("☰", "Меню управления")
        self.hide_button = button("✕", "Скрыть панель", "companionDanger")

        self.mic.clicked.connect(self.mic_clicked.emit)
        self.call.clicked.connect(self.call_clicked.emit)
        self.menu.clicked.connect(self.menu_clicked.emit)
        self.hide_button.clicked.connect(self.close_clicked.emit)

        self.hint = QLabel("перетащите за фигуру")
        self.hint.setObjectName("companionHint")

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 10, 8)
        row.setSpacing(6)
        row.addWidget(self.hint)
        row.addStretch(1)
        row.addWidget(self.mic)
        row.addWidget(self.call)
        row.addWidget(self.menu)
        row.addWidget(self.hide_button)

    def set_muted(self, muted: bool) -> None:
        self.mic.setText("🚫" if muted else "🎙")
        self.mic.setToolTip("Микрофон выключен" if muted else "Микрофон включён")


class CompanionPanel(QWidget):
    """Окно персонажа на рабочем столе."""

    menu_requested = Signal()
    hidden = Signal()
    mic_toggled = Signal(bool)
    call_requested = Signal()

    def __init__(self, settings: Mapping[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Юки — компаньон")
        self.setObjectName("companionRoot")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool                      # без кнопки на панели задач
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(COMPANION_QSS)
        self.setMouseTracking(True)
        self.resize(PANEL_W, PANEL_H)

        self.stage = Stage(self)
        self.character = make_character(self, str((settings or {}).get("character", "")) or None)
        self.dimensional = hasattr(self.character, "react")
        # трёхмерная сцена рисует собственную пыль и свечение — вторые поверх лишние
        self.stage.set_minimal(self.dimensional)
        self.capsule = StatusCapsule(parent=self)
        self.bubble = SpeechBubble(self)
        self.dock = Dock(self)

        layout = QVBoxLayout(self)
        if self.dimensional:
            # на рабочем столе остаётся только фигура: ни рамки, ни подписей,
            # ни кнопок. Всё управление — в правом клике и в главном окне
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(self.character, 1)
            self.capsule.hide()
            self.dock.hide()
        else:
            layout.setContentsMargins(14, 12, 14, 10)
            layout.setSpacing(8)
            layout.addSpacing(78)                      # место под облако реплики
            layout.addWidget(self.capsule)
            layout.addWidget(self.character, 1)
            layout.addWidget(self.dock)

        self._muted = False
        self._subtitles = not self.dimensional

        self._dock_effect = QGraphicsOpacityEffect(self.dock)
        self.dock.setGraphicsEffect(self._dock_effect)
        self._dock_fade = QPropertyAnimation(self._dock_effect, b"opacity", self)
        self._dock_fade.setDuration(240)
        self._dock_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._dock_effect.setOpacity(1.0)
        self._dock_timer = QTimer(self)
        self._dock_timer.setSingleShot(True)
        self._dock_timer.timeout.connect(lambda: self._show_dock(False))

        self.dock.menu_clicked.connect(self.menu_requested.emit)
        self.dock.mic_clicked.connect(self._toggle_mic)
        self.dock.call_clicked.connect(self.call_requested.emit)
        self.dock.close_clicked.connect(self._on_close)
        self.character.clicked.connect(self._on_character_clicked)
        # трёхмерный виджет забирает мышь себе, поэтому просит окно двигаться сам
        if hasattr(self.character, "drag_requested"):
            self.character.drag_requested.connect(self._start_move)

        self.apply_settings(settings or {})
        self._dock_timer.start(DOCK_IDLE_MS)

    # ---------------------------------------------------------------- настройки

    def apply_settings(self, settings: Mapping[str, Any]) -> None:
        """Применяет раздел companion. Вызывается и на старте, и на лету из меню."""
        if self.dimensional:
            # одним пакетом: сцена перестраивается один раз, а не по разу на строку
            character = str(settings.get("character", "")).strip()
            if character:
                self.character.set_character(character)
            self.character.apply({
                "scale": float(settings.get("scale", 1.0)),
                "follow_cursor": bool(settings.get("follow_cursor", True)),
                "idle_motion": bool(settings.get("idle_motion", True)),
                "lip_sync": bool(settings.get("lip_sync", True)),
                "quality": str(settings.get("quality", "high")),
                "framing": str(settings.get("framing", "full")),
            })
        else:
            self.character.set_skin(str(settings.get("voice", "mira")))
            self.character.set_scale(float(settings.get("scale", 1.0)))
            self.character.set_follow_cursor(bool(settings.get("follow_cursor", True)))
            self.character.set_idle_motion(bool(settings.get("idle_motion", True)))
            self.character.set_lip_sync(bool(settings.get("lip_sync", True)))
        self.capsule.set_name(str(settings.get("name", "Мира")))
        # у трёхмерного персонажа облако реплики отключено: вокруг неё не должно
        # быть ни строчки текста
        self._subtitles = bool(settings.get("subtitles", True)) and not self.dimensional

        self.setWindowOpacity(max(0.25, min(1.0, float(settings.get("opacity", 1.0)))))
        on_top = bool(settings.get("always_on_top", True))
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
            if self.isVisible():
                self.show()

        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, bool(settings.get("click_through", False))
        )

        position = settings.get("position")
        if isinstance(position, (list, tuple)) and len(position) == 2:
            self.move(int(position[0]), int(position[1]))
        elif not self.isVisible():
            self.move_to_corner()

    def position(self) -> list[int]:
        return [self.x(), self.y()]

    def move_to_corner(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 28, area.bottom() - self.height() - 12)

    # ---------------------------------------------------------------- события ассистента

    def on_state(self, state: str) -> None:
        self.character.set_state(state)
        if self.dimensional:
            return
        self.stage.set_state(state)
        self.capsule.set_state(state)
        if state in ("listening", "speaking"):
            self._show_dock(True)

    def on_level(self, level: float) -> None:
        self.character.set_level(level)
        if self.dimensional:
            return
        self.stage.set_level(level)
        self.capsule.set_level(level)

    def on_viseme(self, shape: Mapping[str, float]) -> None:
        """Форма рта на текущем блоке речи — только трёхмерный персонаж её понимает."""
        if self.dimensional:
            self.character.set_viseme(shape)

    def on_speech(self, text: str) -> None:
        """Реплика по мере произнесения — субтитр растёт вместе с голосом."""
        if self._subtitles and text.strip():
            self.bubble.show_text(text, _accent("speaking"))

    def on_emotion(self, key: str, shape: str, seconds: float) -> None:
        """Эмоция, разобранная из смысла реплики. Приходит раньше самого текста.

        Ответ печатается в журнал уже после того, как отзвучал, поэтому реакция
        по событию `message` всегда опаздывала на целую фразу. Здесь лицо
        меняется в тот момент, когда персонаж начинает это говорить.
        """
        if self.dimensional:
            self.character.play_emotion(shape, seconds)
        else:
            self.character.play_emotion(key, seconds)

    def on_message(self, kind: str, text: str) -> None:
        if kind == "assistant":
            if self._subtitles:
                self.bubble.show_text(text, _accent("speaking"))
        elif kind == "user":
            self._emote("listening", "attentive", 1.4)
        elif kind == "error":
            if self.dimensional:
                self.character.react("error")
            else:
                self.character.play_emotion("alert", 2.6)
            if self._subtitles:
                self.bubble.show_text(text, _accent("offline"))

    def _emote(self, flat: str, dimensional: str, seconds: float) -> None:
        """Наборы эмоций у рисованного и трёхмерного персонажей разные."""
        self.character.play_emotion(dimensional if self.dimensional else flat, seconds)

    def greet(self) -> None:
        if self.dimensional:
            self.character.react("greet")
            return
        self.character.play_emotion("greeting", 2.8)
        self._show_dock(True)

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self.dock.set_muted(muted)

    # ---------------------------------------------------------------- взаимодействие

    def _show_dock(self, visible: bool) -> None:
        if self.dimensional:
            return
        self._dock_fade.stop()
        self._dock_fade.setStartValue(self._dock_effect.opacity())
        self._dock_fade.setEndValue(1.0 if visible else 0.0)
        self._dock_fade.start()
        if visible:
            self._dock_timer.start(DOCK_IDLE_MS)

    def _on_character_clicked(self) -> None:
        self._show_dock(True)
        choices = ("happy", "surprised", "smile") if self.dimensional else ("happy", "wink", "surprised")
        self.character.play_emotion(random.choice(choices), 2.0)

    def _toggle_mic(self) -> None:
        self._muted = not self._muted
        self.dock.set_muted(self._muted)
        self._emote("shy" if self._muted else "happy",
                    "doubt" if self._muted else "happy", 1.6)
        self.mic_toggled.emit(self._muted)

    def _start_move(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def _on_close(self) -> None:
        self.hide()
        self.hidden.emit()

    def enterEvent(self, event) -> None:
        self._show_dock(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._dock_timer.start(1200)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_move()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction(QAction("Настройки Юки", menu, triggered=self.menu_requested.emit))
        menu.addAction(QAction("Видеосвязь", menu, triggered=self.call_requested.emit))
        emotions_menu = menu.addMenu("Эмоция")
        for key, emotion in EMOTIONS.items():
            emotions_menu.addAction(
                QAction(emotion.title.capitalize(), emotions_menu,
                        triggered=lambda _=False, name=key: self.character.play_emotion(name, 3.0))
            )
        menu.addSeparator()
        menu.addAction(QAction("В угол экрана", menu, triggered=self.move_to_corner))
        menu.addAction(QAction("Скрыть панель", menu, triggered=self._on_close))
        menu.exec(event.globalPos())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.stage.setGeometry(self.rect())
        self.stage.lower()
        self.bubble.raise_()
