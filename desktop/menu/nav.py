"""Боковая навигация пульта: знак, живой статус, разделы с иконками, звонок.

Всё рисуется вручную, без системных кнопок: подсветка выбранного раздела —
отдельный слой, который плавно переезжает к нажатому пункту, а не мгновенно
перекрашивает кнопки. Так навигация ощущается одним живым объектом.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QWidget

from .. import fonts

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover
    QSvgRenderer = None

CYAN = QColor(88, 182, 255)
VIOLET = QColor(139, 108, 255)
INK = QColor(232, 238, 250)
MUTE = QColor(138, 151, 174)

# Линейные иконки 24×24 — одна толщина штриха, как на сайте проекта.
ICONS: dict[str, str] = {
    "dialog": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    "messages": '<path d="M21 3L10 14"/><path d="M21 3l-7 18-4-7-7-4z"/>',
    "scenarios": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "playlist": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "memory": '<path d="M12 3a6 6 0 0 0-6 6c0 2.2 1.2 3.6 2.4 4.6.8.7 1.1 1.4 1.1 2.4v1h5v-1c0-1 .3-1.7 1.1-2.4C16.8 12.6 18 11.2 18 9a6 6 0 0 0-6-6z"/><path d="M9.5 20h5M10.5 22.5h3"/>',
    "agent": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16"/>',
    "voice": '<path d="M3 12h2M7 8v8M11 4v16M15 7v10M19 10v4M21 12h0"/>',
    "character": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/><path d="M18 3l1 2 2 1-2 1-1 2-1-2-2-1 2-1z"/>',
    "ai": '<rect x="6" y="6" width="12" height="12" rx="2.5"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "language": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
    "account": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="10" r="3.2"/><path d="M6.5 18.5c1.4-2.2 3.3-3.3 5.5-3.3s4.1 1.1 5.5 3.3"/>',
    "call": '<rect x="2.5" y="6" width="13" height="12" rx="3"/><path d="M15.5 10.5l6-3.5v10l-6-3.5z"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "minimize": '<path d="M6 12h12"/>',
}


def render_icon(painter: QPainter, key: str, rect: QRectF, color: QColor, width: float = 1.8) -> None:
    """Рисует иконку нужным цветом. Без QtSvg — просто ничего не рисует."""
    body = ICONS.get(key)
    if body is None or QSvgRenderer is None:
        return
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color.name()}" stroke-opacity="{color.alphaF():.2f}" stroke-width="{width}" '
           f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, rect)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


class _Hover:
    """Плавное наведение 0→1 для кнопок, которые рисуют себя сами."""

    def __init__(self, widget: QWidget, duration: int = 220) -> None:
        self.value = 0.0
        self._widget = widget
        self._anim = QVariantAnimation(widget)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set)

    def _set(self, value: float) -> None:
        self.value = float(value)
        self._widget.update()

    def go(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(float(target))
        self._anim.start()


# ---------------------------------------------------------------- знак

class BrandMark(QWidget):
    """Знак Y в кольце и медленное кольцо телеметрии вокруг — как на сайте."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(64)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._phase += 0.008
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(30, 32)

        glow = QRadialGradient(c, 34)
        glow.setColorAt(0.0, QColor(88, 182, 255, 70))
        glow.setColorAt(1.0, QColor(88, 182, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(c, 34, 34)

        # кольцо телеметрии: штрихи, бегущие по кругу
        for i in range(36):
            angle = self._phase + i * math.tau / 36
            if i % 3 == 2:
                continue
            alpha = int(60 + 90 * (0.5 + 0.5 * math.sin(angle * 2 - self._phase * 3)))
            painter.setPen(QPen(QColor(139, 160, 255, alpha), 1.4))
            r1, r2 = 25.5, 27.5 if i % 6 else 29.0
            painter.drawLine(QPointF(c.x() + math.cos(angle) * r1, c.y() + math.sin(angle) * r1),
                             QPointF(c.x() + math.cos(angle) * r2, c.y() + math.sin(angle) * r2))

        painter.setPen(QPen(CYAN, 2.2))
        painter.setBrush(QColor(6, 12, 28))
        painter.drawEllipse(c, 20, 20)
        path = QPainterPath()
        path.moveTo(c.x() - 8.5, c.y() - 9)
        path.lineTo(c.x(), c.y() + 1)
        path.lineTo(c.x() + 8.5, c.y() - 9)
        path.moveTo(c.x(), c.y() + 1)
        path.lineTo(c.x(), c.y() + 11)
        pen = QPen(QColor(255, 255, 255), 3.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.setPen(INK)
        painter.setFont(fonts.font(fonts.DISPLAY, 15, QFont.Weight.Bold, 4.5))
        painter.drawText(QRectF(72, 12, self.width() - 72, 24), Qt.AlignmentFlag.AlignVCenter, "YUKI")
        painter.setPen(QColor(88, 182, 255, 210))
        painter.setFont(fonts.font(fonts.MONO, 7.2, QFont.Weight.Medium, 2.2))
        painter.drawText(QRectF(73, 36, self.width() - 72, 16), Qt.AlignmentFlag.AlignVCenter, "CONTROL DECK")
        painter.end()


# ---------------------------------------------------------------- живой статус

_STATE_TITLES = {
    "idle": "На связи", "listening": "Слушаю", "thinking": "Думаю",
    "speaking": "Говорю", "offline": "Ядро спит", "muted": "Микрофон выкл",
}
_STATE_COLORS = {
    "idle": QColor(120, 180, 255), "listening": QColor(88, 200, 255), "thinking": QColor(160, 130, 255),
    "speaking": QColor(95, 240, 192), "offline": QColor(255, 107, 133), "muted": QColor(255, 180, 92),
}


class StatusCard(QWidget):
    """Стеклянная карточка с мини-ядром из частиц, состоянием и моделью."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(92)
        self._state = "idle"
        self._level = 0.0
        self._shown_level = 0.0
        self._model = "модель…"
        self._online = True
        self._phase = 0.0
        rand = random.Random(7)
        # точки на сфере: (широта, долгота, яркость)
        self._dots = [(math.acos(1 - 2 * (i + 0.5) / 140), i * math.pi * (3 - math.sqrt(5)), rand.random())
                      for i in range(140)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_state(self, state: str) -> None:
        self._state = state if state in _STATE_TITLES else "idle"
        self.update()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def set_model(self, name: str, online: bool) -> None:
        self._model, self._online = name or "—", bool(online)
        self.update()

    def _tick(self) -> None:
        if not self.isVisible():
            return
        speed = {"thinking": 2.2, "speaking": 1.6, "listening": 1.2}.get(self._state, 0.7)
        self._phase += 0.008 * speed
        self._shown_level += (self._level - self._shown_level) * 0.14
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        state = self._state if self._online else "offline"
        tone = _STATE_COLORS[state]

        body = QLinearGradient(rect.topLeft(), rect.bottomRight())
        body.setColorAt(0.0, QColor(22, 34, 66, 200))
        body.setColorAt(1.0, QColor(8, 12, 26, 210))
        painter.setBrush(body)
        edge = QLinearGradient(rect.topLeft(), rect.topRight())
        edge.setColorAt(0.0, QColor(tone.red(), tone.green(), tone.blue(), 120))
        edge.setColorAt(1.0, QColor(139, 108, 255, 40))
        painter.setPen(QPen(edge, 1))
        painter.drawRoundedRect(rect, 16, 16)

        # мини-ядро: вращающаяся сфера из точек, дышит громкостью
        c = QPointF(46, rect.center().y())
        radius = 26 + self._shown_level * 6
        glow = QRadialGradient(c, radius * 1.6)
        glow.setColorAt(0.0, QColor(tone.red(), tone.green(), tone.blue(), 90))
        glow.setColorAt(1.0, QColor(tone.red(), tone.green(), tone.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(c, radius * 1.6, radius * 1.6)
        spin = self._phase
        for theta, phi, bright in self._dots:
            wobble = 1 + 0.08 * math.sin(theta * 5 + self._phase * 4) * (0.4 + self._shown_level * 2)
            x = math.sin(theta) * math.cos(phi + spin)
            y = math.cos(theta)
            z = math.sin(theta) * math.sin(phi + spin)
            depth = (z + 1) / 2
            color = _mix(QColor(88, 182, 255), QColor(160, 130, 255), 0.5 + y * 0.5)
            color = _mix(color, tone, 0.35)
            color.setAlpha(int(40 + 190 * depth * (0.5 + 0.5 * bright)))
            painter.setBrush(color)
            size = 0.7 + 1.2 * depth
            painter.drawEllipse(QPointF(c.x() + x * radius * wobble, c.y() + y * radius * wobble * 0.98), size, size)

        left = 88.0
        painter.setPen(QColor(tone.red(), tone.green(), tone.blue()))
        painter.setFont(fonts.font(fonts.MONO, 6.8, QFont.Weight.Bold, 1.8))
        painter.drawText(QRectF(left, 16, rect.width() - left, 14), Qt.AlignmentFlag.AlignVCenter, "СОСТОЯНИЕ")
        painter.setPen(INK)
        painter.setFont(fonts.font(fonts.DISPLAY, 11.5, QFont.Weight.Bold))
        painter.drawText(QRectF(left, 30, rect.width() - left - 8, 24), Qt.AlignmentFlag.AlignVCenter,
                         _STATE_TITLES[state])
        painter.setPen(MUTE)
        painter.setFont(fonts.font(fonts.MONO, 7.4, QFont.Weight.Medium))
        model = self._model if self._online else "запусти ollama serve"
        painter.drawText(QRectF(left, 56, rect.width() - left - 8, 18), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(model, Qt.TextElideMode.ElideRight, int(rect.width() - left - 8)))
        painter.end()


# ---------------------------------------------------------------- пункт раздела

class NavButton(QAbstractButton):
    """Пункт навигации: иконка, название; подсветку выбранного рисует NavHighlight."""

    def __init__(self, key: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setText(title)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"hover", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    def _fade(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event) -> None:
        self._fade(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._fade(0.0)
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(220, 46)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        active = self.isChecked()
        if not active and self._hover > 0.01:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(120, 160, 255, int(22 * self._hover)))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 12, 12)

        icon_color = QColor(255, 255, 255) if active else _mix(QColor(138, 151, 174), CYAN, self._hover)
        render_icon(painter, self.key, QRectF(18, rect.center().y() - 10, 20, 20), icon_color,
                    2.0 if active else 1.7)

        painter.setPen(QColor(255, 255, 255) if active else _mix(QColor(185, 196, 216), INK, self._hover))
        painter.setFont(fonts.font(fonts.SANS, 10.5, QFont.Weight.DemiBold if active else QFont.Weight.Medium))
        painter.drawText(QRectF(50, 0, rect.width() - 70, rect.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        if active:
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1.6))
            x, y = rect.right() - 20, rect.center().y()
            painter.drawLine(QPointF(x - 3, y - 4), QPointF(x + 1, y))
            painter.drawLine(QPointF(x + 1, y), QPointF(x - 3, y + 4))
        painter.end()


class NavHighlight(QWidget):
    """Светящаяся плашка под выбранным пунктом. Переезжает, а не перескакивает."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(520)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._phase += 0.06
        self.update()

    def move_to(self, target: QRect, animate: bool = True) -> None:
        self._anim.stop()
        if not animate or self.geometry().isEmpty():
            self.setGeometry(target)
            return
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        fill = QLinearGradient(rect.topLeft(), rect.topRight())
        fill.setColorAt(0.0, QColor(88, 182, 255, 70))
        fill.setColorAt(0.6, QColor(139, 108, 255, 46))
        fill.setColorAt(1.0, QColor(139, 108, 255, 16))
        painter.setBrush(fill)
        border = QLinearGradient(rect.topLeft(), rect.topRight())
        shimmer = 0.5 + 0.5 * math.sin(self._phase)
        border.setColorAt(0.0, QColor(120, 200, 255, int(140 + 60 * shimmer)))
        border.setColorAt(1.0, QColor(139, 108, 255, 40))
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 12, 12)
        bar = QLinearGradient(0, rect.top(), 0, rect.bottom())
        bar.setColorAt(0.0, CYAN)
        bar.setColorAt(1.0, VIOLET)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bar)
        painter.drawRoundedRect(QRectF(rect.left() + 2, rect.top() + 11, 3, rect.height() - 22), 1.5, 1.5)
        painter.end()


# ---------------------------------------------------------------- звонок

class CallButton(QAbstractButton):
    """Главное действие пульта: большая градиентная кнопка с бегущим бликом."""

    def __init__(self, text: str, hint: str = "Ctrl+D", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self._hint = hint
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)
        self._phase = 0.0
        self._hover = _Hover(self, 260)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.004) % 1.6
        self.update()

    def enterEvent(self, event) -> None:
        self._hover.go(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.go(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        lift = int(28 * self._hover.value)
        grad.setColorAt(0.0, QColor(min(255, 124 + lift), min(255, 199 + lift), 255))
        grad.setColorAt(1.0, QColor(min(255, 164 + lift), min(255, 141 + lift), 255))
        path = QPainterPath()
        path.addRoundedRect(rect, 15, 15)
        if self._hover.value > 0.01:
            halo = QRadialGradient(rect.center(), rect.width() * 0.7)
            halo.setColorAt(0.0, QColor(140, 170, 255, int(70 * self._hover.value)))
            halo.setColorAt(1.0, QColor(140, 170, 255, 0))
            painter.fillRect(self.rect(), halo)
        painter.fillPath(path, grad)
        # блик пробегает по кнопке раз в пару секунд
        x = rect.left() + (self._phase - 0.3) * rect.width()
        shine = QLinearGradient(x - 40, 0, x + 40, 0)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QColor(255, 255, 255, 90))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, shine)
        painter.restore()

        ink = QColor(4, 16, 34)
        render_icon(painter, "call", QRectF(18, rect.center().y() - 10, 20, 20), ink, 2.0)
        painter.setPen(ink)
        painter.setFont(fonts.font(fonts.SANS, 10.5, QFont.Weight.Bold))
        painter.drawText(QRectF(48, 0, rect.width() - 110, rect.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.setFont(fonts.font(fonts.MONO, 7.4, QFont.Weight.Bold))
        badge = QRectF(rect.right() - 62, rect.center().y() - 11, 52, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(4, 16, 34, 40))
        painter.drawRoundedRect(badge, 7, 7)
        painter.setPen(QColor(4, 16, 34, 200))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self._hint)
        painter.end()


class IconButton(QAbstractButton):
    """Маленькая кнопка окна (свернуть, закрыть) с иконкой."""

    def __init__(self, key: str, danger: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._danger = danger
        self._hover = _Hover(self, 200)
        self.setFixedSize(38, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event) -> None:
        self._hover.go(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover.go(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        t = self._hover.value
        hot_fill = QColor(255, 90, 120, 60) if self._danger else QColor(120, 160, 255, 40)
        hot_edge = QColor(255, 107, 133, 150) if self._danger else QColor(88, 182, 255, 140)
        painter.setBrush(_mix(QColor(12, 20, 40, 150), hot_fill, t))
        painter.setPen(QPen(_mix(QColor(150, 180, 255, 45), hot_edge, t), 1))
        painter.drawRoundedRect(rect, 11, 11)
        render_icon(painter, self.key, QRectF(rect.center().x() - 8, rect.center().y() - 8, 16, 16),
                    _mix(QColor(185, 196, 216), QColor(255, 255, 255), t), 2.0)
        painter.end()


class SectionTile(QWidget):
    """Плитка с иконкой текущего раздела в шапке: светится цветом ядра."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(58, 58)
        self._key = "dialog"

    def set_key(self, key: str) -> None:
        self._key = key
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        glow = QRadialGradient(rect.center(), rect.width() * 0.8)
        glow.setColorAt(0.0, QColor(88, 182, 255, 60))
        glow.setColorAt(1.0, QColor(88, 182, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(rect.center(), rect.width() * 0.8, rect.width() * 0.8)
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        fill.setColorAt(0.0, QColor(40, 80, 170, 200))
        fill.setColorAt(1.0, QColor(70, 45, 150, 200))
        painter.setBrush(fill)
        edge = QLinearGradient(rect.topLeft(), rect.bottomRight())
        edge.setColorAt(0.0, QColor(140, 210, 255, 200))
        edge.setColorAt(1.0, QColor(160, 130, 255, 80))
        painter.setPen(QPen(edge, 1.2))
        painter.drawRoundedRect(rect, 15, 15)
        render_icon(painter, self._key, QRectF(rect.center().x() - 12, rect.center().y() - 12, 24, 24),
                    QColor(255, 255, 255), 1.9)
        painter.end()
