"""Виджеты оболочки: шапка, индикатор состояния, лента диалога, поле ввода, подпись автора."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import AUTHOR, KIND_COLORS, KIND_LABELS, STATE_COLORS, STATE_LABELS

MAX_MESSAGES = 60


def chrome_button(glyph: str, tooltip: str, *, danger: bool = False) -> QPushButton:
    button = QPushButton(glyph)
    button.setObjectName("chrome")
    button.setToolTip(tooltip)
    button.setFixedSize(28, 24)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setProperty("danger", "true" if danger else "false")
    return button


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("rule")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


class StatusPill(QWidget):
    """Индикатор состояния: квадратный маркер и моноширинная подпись."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusPill")
        # без этого флага QSS-фон у собственного QWidget не рисуется
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dot = QLabel()
        self._dot.setFixedSize(7, 7)
        self._text = QLabel(STATE_LABELS["idle"])
        self._text.setObjectName("statusText")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 12, 5)
        layout.setSpacing(9)
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        self.set_state("idle")

        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._breathe)
        self._pulse.start(60)
        self._phase = 0.0
        self._color = STATE_COLORS["idle"]

    def set_state(self, state: str) -> None:
        self._color = STATE_COLORS.get(state, STATE_COLORS["idle"])
        self._text.setText(STATE_LABELS.get(state, state.upper()))

    def _breathe(self) -> None:
        """Маркер медленно пульсирует — видно, что ассистент жив."""
        self._phase += 0.12
        alpha = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        color = QColor(self._color)
        color.setAlphaF(alpha)
        self._dot.setStyleSheet(
            f"background: rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f});"
            " border-radius: 1px;"
        )


class LevelMeter(QWidget):
    """Живой эквалайзер: полосы идут от центра и дышат в такт голосу."""

    BARS = 48

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(34)
        self._level = 0.0
        self._phase = 0.0
        self._color = QColor(STATE_COLORS["idle"])
        self._noise = [random.random() for _ in range(self.BARS)]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def set_state(self, state: str) -> None:
        self._color = QColor(STATE_COLORS.get(state, STATE_COLORS["idle"]))

    def _tick(self) -> None:
        self._phase += 0.09
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802 — Qt-нейминг
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        width = self.width() / self.BARS
        middle = self.height() / 2
        base = 0.10 + self._level * 0.90

        for index in range(self.BARS):
            distance = abs(index - self.BARS / 2) / (self.BARS / 2)
            envelope = (1.0 - distance) ** 1.5
            wave = 0.5 + 0.5 * math.sin(self._phase * (1.0 + self._noise[index]) + index * 0.35)
            height = max(2.0, self.height() * base * envelope * (0.35 + 0.65 * wave))

            color = QColor(self._color)
            color.setAlphaF(0.16 + 0.62 * envelope * (0.35 + 0.65 * self._level))
            painter.setBrush(color)
            painter.drawRoundedRect(
                int(index * width + 1), int(middle - height / 2),
                max(1, int(width - 2)), int(height), 1, 1,
            )
        painter.end()


class MetricsLabel(QLabel):
    """Строка телеметрии в футере: процессор, память, громкость."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hint")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2500)
        self._refresh()

    def _refresh(self) -> None:
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory().percent
            # ширина поля постоянна. С «06.0» против «100.0» строка меняла длину
            # каждые две с половиной секунды, вместе с ней менялся желаемый
            # размер страницы — и безрамочное окно от этого уползало вбок
            parts = [f"CPU {cpu:5.1f}%", f"RAM {memory:5.1f}%"]
        except Exception:  # noqa: BLE001 — телеметрия не критична
            parts = []

        try:
            from core.automation import volume_get

            parts.append(f"VOL {volume_get():3d}%")
        except Exception:  # noqa: BLE001
            pass

        self.setText("  ·  ".join(parts))
        # длина строки постоянна, но набор блоков может измениться (нет psutil,
        # пропала громкость) — фиксируем максимум, чтобы окно не дышало
        self.setMinimumWidth(max(self.minimumWidth(), self.sizeHint().width()))


class MessageCard(QFrame):
    def __init__(self, kind: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setProperty("kind", kind)

        who = QLabel(KIND_LABELS.get(kind, kind).upper())
        who.setProperty("role", "who")
        who.setStyleSheet(f"color: {KIND_COLORS.get(kind, KIND_COLORS['system'])};")

        body = QLabel(text)
        body.setProperty("role", "body")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 8, 13, 10)
        layout.setSpacing(3)
        layout.addWidget(who)
        layout.addWidget(body)


class ChatLog(QScrollArea):
    """Лента реплик, прижатая к низу; старые сообщения вытесняются."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("logScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(0, 0, 8, 0)
        self._layout.setSpacing(7)
        self._layout.addStretch(1)
        self.setWidget(container)

    def add_message(self, kind: str, text: str) -> None:
        card = MessageCard(kind, text)
        self._layout.addWidget(card)

        # плавное появление: карточка проявляется, а не выскакивает
        effect = QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", card)
        animation.setDuration(260)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        while self._layout.count() > MAX_MESSAGES + 1:
            item = self._layout.takeAt(1)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class Composer(QWidget):
    """Ввод команды текстом и переключатель микрофона."""

    submitted = Signal(str)
    mic_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Команда — Enter")
        self.input.returnPressed.connect(self._submit)

        send = QPushButton("ВЫПОЛНИТЬ")
        send.setObjectName("action")
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.clicked.connect(self._submit)

        self.mic = QPushButton("МИКРОФОН ВКЛ")
        self.mic.setObjectName("action")
        self.mic.setCheckable(True)
        self.mic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic.toggled.connect(self._on_mic)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.input, 1)
        layout.addWidget(send)
        layout.addWidget(self.mic)

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.submitted.emit(text)

    def _on_mic(self, muted: bool) -> None:
        self.mic.setText("МИКРОФОН ВЫКЛ" if muted else "МИКРОФОН ВКЛ")
        self.mic_toggled.emit(muted)

    def set_muted(self, muted: bool) -> None:
        if self.mic.isChecked() != muted:
            self.mic.setChecked(muted)


class VoiceSelector(QWidget):
    """Выбор голоса и кнопка пробы. Список берётся из core.voices, а не зашит в интерфейс."""

    voice_changed = Signal(str)
    preview_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from core import voices

        self._profiles = voices.catalog()
        self._muted_signal = False

        self.box = QComboBox()
        self.box.setObjectName("voiceBox")
        self.box.setCursor(Qt.CursorShape.PointingHandCursor)
        for profile in self._profiles:
            label = profile.title if profile.installed else f"{profile.title} (нет файла)"
            self.box.addItem(label, profile.key)
            self.box.setItemData(
                self.box.count() - 1, f"{profile.character} · {profile.model_name}", Qt.ItemDataRole.ToolTipRole
            )
        self.box.currentIndexChanged.connect(self._on_changed)

        caret = QLabel("▾")
        caret.setObjectName("hint")
        caret.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.preview = chrome_button("▶", "Послушать голос")
        self.preview.clicked.connect(lambda: self.preview_requested.emit(self.current_key()))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.box)
        layout.addWidget(caret)
        layout.addWidget(self.preview)

    def current_key(self) -> str:
        return str(self.box.currentData() or "")

    def set_current(self, key: str) -> None:
        """Синхронизация с ассистентом: голос могли переключить голосом или командой."""
        index = self.box.findData(key)
        if index < 0 or index == self.box.currentIndex():
            return
        self._muted_signal = True
        self.box.setCurrentIndex(index)
        self._muted_signal = False

    def _on_changed(self, index: int) -> None:
        if self._muted_signal:
            return
        key = str(self.box.itemData(index) or "")
        if key:
            self.voice_changed.emit(key)




def make_tray_icon(size: int = 64) -> QPixmap:
    """Тот же знак, что и в assets/yuki.ico: тёмный диск, синий кант, белая «Y».

    Рисуется кодом, чтобы трей не зависел от файла на диске, и повторяет иконку
    приложения — в трее и на панели задач должно быть видно одно и то же.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    inset = size * 0.05
    disc = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(6, 10, 20))
    painter.drawEllipse(disc)

    # кант вместо размытия: на 16 пикселях мягкое свечение всё равно не читается
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(96, 178, 255), max(1.0, size * 0.05)))
    painter.drawEllipse(disc)

    pen = QPen(QColor(238, 246, 255), max(1.5, size * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    centre, top, fork, bottom, span = size / 2, size * 0.34, size * 0.53, size * 0.70, size * 0.15
    painter.drawLine(QPointF(centre - span, top), QPointF(centre, fork))
    painter.drawLine(QPointF(centre + span, top), QPointF(centre, fork))
    painter.drawLine(QPointF(centre, fork), QPointF(centre, bottom))
    painter.end()
    return pixmap
