"""Элементы меню: стеклянные карточки, строки настроек, переключатели, слайдеры.

Всё нарисовано под одну эстетику: чёрный космос, мягкое свечение, тонкие рамки,
никаких системных виджетов «как в проводнике».
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class GlassToggle(QWidget):
    """Переключатель: капля скользит по стеклянной дорожке, свечение зажигается плавно."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(56, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._progress = 1.0 if checked else 0.0

        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        self._animate()

    def _animate(self) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(1.0 if self._checked else 0.0)
        self._animation.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self._animate()
            self.toggled.emit(self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 3, self.width() - 2, self.height() - 6)
        t = self._progress

        # выключен — тёмная стеклянная дорожка; включён — градиент ядра
        painter.setPen(QPen(QColor(130, 170, 255, int(60 + 60 * (1 - t))), 1))
        painter.setBrush(QColor(10, 16, 32, 230))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        if t > 0.01:
            fill = QLinearGradient(track.topLeft(), track.topRight())
            fill.setColorAt(0.0, QColor(88, 182, 255, int(230 * t)))
            fill.setColorAt(1.0, QColor(139, 108, 255, int(230 * t)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        knob_x = track.left() + 11 + (track.width() - 22) * t
        glow = QColor(140, 200, 255)
        glow.setAlphaF(0.35 * t)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(knob_x, track.center().y()), 14, 14)
        painter.setBrush(QColor(255, 255, 255) if self._checked else QColor(150, 168, 195))
        painter.drawEllipse(QPointF(knob_x, track.center().y()), 8.5, 8.5)
        painter.end()


class Card(QFrame):
    """Стеклянная карточка с заголовком: внутрь складываются строки настроек."""

    def __init__(self, title: str, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("menuCard")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 16, 20, 18)
        self._layout.setSpacing(10)

        head = QLabel(title.upper())
        head.setObjectName("cardTitle")
        self._layout.addWidget(head)
        if hint:
            note = QLabel(hint)
            note.setObjectName("cardHint")
            note.setWordWrap(True)
            self._layout.addWidget(note)

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        self._mark_last_row()
        return widget

    def add_all(self, widgets: Iterable[QWidget]) -> None:
        for widget in widgets:
            self.add(widget)

    def _mark_last_row(self) -> None:
        """У последней строки карточки разделителя быть не должно.

        Линия между строками помогает вести глаз, но под нижней строкой она
        превращается в лишнюю черту у самого края карточки.
        """
        rows = [self._layout.itemAt(index).widget() for index in range(self._layout.count())]
        rows = [item for item in rows if isinstance(item, Row)]
        for position, row in enumerate(rows):
            row.setProperty("last", "true" if position == len(rows) - 1 else "false")
            row.style().unpolish(row)
            row.style().polish(row)


class Row(QWidget):
    """Строка настройки: подпись слева, элемент управления справа."""

    def __init__(self, label: str, control: QWidget, hint: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("menuRow")
        # без этого флага QSS-рамка у собственного QWidget не рисуется
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.control = control

        title = QLabel(label)
        title.setObjectName("rowLabel")

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(title)
        if hint:
            note = QLabel(hint)
            note.setObjectName("rowHint")
            note.setWordWrap(True)
            text.addWidget(note)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 10, 0, 11)
        row.setSpacing(18)
        row.addLayout(text, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


def toggle_row(label: str, hint: str, checked: bool) -> tuple[Row, GlassToggle]:
    control = GlassToggle(checked)
    return Row(label, control, hint), control


def select_row(label: str, hint: str, items: Sequence[tuple[str, str]],
               current: str) -> tuple[Row, QComboBox]:
    """items: пары (значение, подпись)."""
    box = QComboBox()
    box.setObjectName("menuSelect")
    box.setCursor(Qt.CursorShape.PointingHandCursor)
    for value, title in items:
        box.addItem(title, value)
    index = box.findData(current)
    if index >= 0:
        box.setCurrentIndex(index)
    return Row(label, box, hint), box


def slider_row(label: str, hint: str, value: float, minimum: int = 0,
               maximum: int = 100) -> tuple[Row, QSlider, QLabel]:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setObjectName("menuSlider")
    slider.setMinimum(minimum)
    slider.setMaximum(maximum)
    slider.setValue(int(value))
    slider.setFixedWidth(168)
    slider.setCursor(Qt.CursorShape.PointingHandCursor)

    # значение ползунка — отдельной плашкой: так видно, что это именно число
    # настройки, а не случайная подпись рядом
    readout = QLabel(f"{int(value)}")
    readout.setObjectName("rowValue")
    readout.setFixedWidth(46)
    readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    slider.valueChanged.connect(lambda number: readout.setText(str(number)))

    holder = QWidget()
    line = QHBoxLayout(holder)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(10)
    line.addWidget(slider)
    line.addWidget(readout)
    return Row(label, holder, hint), slider, readout


def input_row(label: str, hint: str, value: str, placeholder: str = "") -> tuple[Row, QLineEdit]:
    field = QLineEdit(value)
    field.setObjectName("menuInput")
    field.setPlaceholderText(placeholder)
    return Row(label, field, hint), field


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet("background: rgba(120, 170, 255, 0.10); border: none;")


class Starfield(QWidget):
    """Фон меню: медленная звёздная пыль и два далёких свечения.

    Рисуется в отдельном виджете под содержимым, поэтому не мешает ни одному
    элементу интерфейса и стоит почти ничего: полсотни точек на кадр.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._phase = 0.0
        self._stars: list[tuple[float, float, float, float]] = []
        self._seed()

        from PySide6.QtCore import QTimer

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _seed(self) -> None:
        import random

        self._stars = [
            (random.random(), random.random(), random.uniform(0.5, 1.8), random.uniform(0.2, 1.0))
            for _ in range(110)
        ]

    def _tick(self) -> None:
        self._phase += 0.02
        self.update()

    def paintEvent(self, event) -> None:
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()

        painter.setPen(Qt.PenStyle.NoPen)
        base = QLinearGradient(0, 0, 0, height)
        base.setColorAt(0.0, QColor(5, 8, 18))
        base.setColorAt(1.0, QColor(3, 4, 10))
        painter.setBrush(base)
        painter.drawRect(0, 0, width, height)

        # две туманности медленно дышат: голубая сверху справа, фиолетовая снизу слева
        breathe = 0.5 + 0.5 * math.sin(self._phase * 0.6)
        for cx, cy, radius, color, alpha in (
            (0.78, 0.08, 0.62, (40, 110, 230), 70 + 30 * breathe),
            (0.30, 1.02, 0.70, (110, 60, 220), 60 + 30 * (1 - breathe)),
            (0.55, 0.55, 0.45, (30, 60, 140), 22),
        ):
            glow = QRadialGradient(QPointF(cx * width, cy * height), radius * max(width, height))
            glow.setColorAt(0.0, QColor(*color, int(alpha)))
            glow.setColorAt(1.0, QColor(*color, 0))
            painter.setBrush(glow)
            painter.drawRect(0, 0, width, height)

        for x, y, size, speed in self._stars:
            twinkle = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(self._phase * speed * 2.4 + x * 30))
            painter.setBrush(QColor(180, 214, 255, int(120 * twinkle)))
            painter.drawEllipse(
                QPointF(x * width, (y * height + self._phase * speed * 6) % height), size, size
            )
        painter.end()
