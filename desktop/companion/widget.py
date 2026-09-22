"""Виджет с живым персонажем: 60 кадров в секунду поверх любого фона.

Виджет умышленно ничего не знает про ассистента — ему передают состояние,
громкость и эмоцию. Так его можно поставить и в панель на рабочем столе, и в
превью настроек, и позже в окно видеосвязи.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import QWidget

from ..theme import STATE_COLORS
from .animator import Animator
from .photo import PhotoRig
from .rig import CANVAS_H, CANVAS_W, draw_character
from .skin import DEFAULT_SKIN, Skin, variant

_PHOTO: PhotoRig | None = None


def photo_rig() -> PhotoRig:
    """Слои референса читаются один раз на всё приложение — они немаленькие."""
    global _PHOTO
    if _PHOTO is None:
        _PHOTO = PhotoRig()
    return _PHOTO


class CharacterWidget(QWidget):
    """Рисует персонажа и сам крутит её анимацию."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, skin: Skin | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMinimumSize(180, 270)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.animator = Animator()
        self._skin = skin or DEFAULT_SKIN
        self._state = "idle"
        # по умолчанию на экране живёт оригинальный рисунок; вектор — запасной путь
        self._photo = photo_rig()
        self._use_photo = self._photo.available

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_fps(60)

    # ---------------------------------------------------------------- внешнее API

    def set_fps(self, fps: int) -> None:
        """Частота кадров: на слабой машине панель можно сделать экономнее."""
        self._timer.start(max(8, int(1000 / max(10, min(120, fps)))))

    def set_state(self, state: str) -> None:
        self._state = state
        self.animator.set_state(state)
        self._skin = self._skin.with_aura(QColor(STATE_COLORS.get(state, STATE_COLORS["idle"])))

    def set_level(self, level: float) -> None:
        self.animator.set_level(level)

    def play_emotion(self, key: str, seconds: float = 2.4) -> None:
        self.animator.play(key, seconds)

    def set_skin(self, key: str) -> None:
        aura = self._skin.aura
        self._skin = variant(key).with_aura(aura)

    def set_scale(self, scale: float) -> None:
        self.animator.pose.scale = max(0.5, min(1.6, float(scale)))

    def set_follow_cursor(self, enabled: bool) -> None:
        self.animator.follow_cursor = enabled
        if not enabled:
            self.animator.release_look()

    def set_idle_motion(self, enabled: bool) -> None:
        self.animator.idle_motion = enabled

    def set_lip_sync(self, enabled: bool) -> None:
        self.animator.lip_sync = enabled

    @property
    def emotion_title(self) -> str:
        return self.animator.emotion.title

    # ---------------------------------------------------------------- кадр

    def _tick(self) -> None:
        if self.animator.follow_cursor and self.isVisible():
            self._track_cursor()
        self.animator.step()
        self.update()

    def _track_cursor(self) -> None:
        """Взгляд идёт за курсором в координатах экрана — персонаж «видит» руку человека."""
        cursor = QCursor.pos()
        center = self.mapToGlobal(self.rect().center())
        span = max(320.0, float(self.width()))
        self.animator.look_at(
            (cursor.x() - center.x()) / (span * 1.6),
            (cursor.y() - center.y()) / (span * 1.6),
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        area = QRectF(self.rect())
        if self._use_photo:
            self._photo.draw(painter, area, self.animator.pose, self._phase(), self._skin.aura)
        else:
            draw_character(painter, area, self.animator.pose, self._skin, phase=self._phase())
        painter.end()

    def _phase(self) -> float:
        from time import monotonic

        return monotonic()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.animator.play("happy", 1.8)
            self.clicked.emit()
        super().mousePressEvent(event)

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(int(CANVAS_W / 3), int(CANVAS_H / 3))

    def head_center(self) -> QPointF:
        """Где на виджете находится голова — панель вешает над ней облако реплики."""
        factor = min(self.width() / CANVAS_W, self.height() / CANVAS_H)
        left = self.rect().center().x() - CANVAS_W * factor / 2.0
        top = self.rect().bottom() - CANVAS_H * factor
        return QPointF(left + 500 * factor, top + 300 * factor)
