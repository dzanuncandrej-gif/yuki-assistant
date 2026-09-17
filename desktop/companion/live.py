"""Живой персонаж для панели: GPU-риг плюс аниматор в одном виджете.

Снаружи выглядит так же, как рисованный `CharacterWidget`: те же методы, те же
состояния. Внутри — `QOpenGLWidget`, который деформирует оригинальный рисунок на
видеокарте. Если шейдер не собрался (старый драйвер, нет ассетов), панель просто
берёт запасной виджет — приложение остаётся рабочим.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..theme import STATE_COLORS
from .animator import Animator
from .gl import GLCharacter, assets_ready


class LiveCharacter(QWidget):
    """Персонаж, нарисованный видеокартой, с той же логикой жизни, что и раньше."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(200, 300)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.animator = Animator()
        self.view = GLCharacter(self)
        self.available = self.view.available

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_fps(60)

    # ---------------------------------------------------------------- API панели

    def set_fps(self, fps: int) -> None:
        self._timer.start(max(8, int(1000 / max(10, min(144, fps)))))

    def set_state(self, state: str) -> None:
        self.animator.set_state(state)
        self.view.set_accent(QColor(STATE_COLORS.get(state, STATE_COLORS["idle"])))

    def set_level(self, level: float) -> None:
        self.animator.set_level(level)

    def play_emotion(self, key: str, seconds: float = 2.4) -> None:
        self.animator.play(key, seconds)

    def set_skin(self, key: str) -> None:
        """Внешность задаёт сам рисунок — ключ голоса на неё не влияет."""

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
        now = time.monotonic()
        delta = min(0.1, now - self._last)
        self._last = now

        if self.animator.follow_cursor and self.isVisible():
            cursor = QCursor.pos()
            center = self.mapToGlobal(self.rect().center())
            span = max(320.0, float(self.width()))
            self.animator.look_at(
                (cursor.x() - center.x()) / (span * 1.6),
                (cursor.y() - center.y()) / (span * 1.6),
            )

        pose = self.animator.step()
        self.view.set_pose(pose)
        self.view.advance(delta)
        self.view.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802 — Qt-нейминг
        if event.button() == Qt.MouseButton.LeftButton:
            self.animator.play("happy", 1.8)
            self.clicked.emit()
        super().mousePressEvent(event)


def make_character(parent: QWidget | None = None, character: str | None = None) -> QWidget:
    """Выбирает лучшего доступного персонажа.

    Сначала трёхмерная модель со скелетом и мимикой, если она собрана и движок
    отображения на месте. Затем прежний GPU-риг по рисунку. В самом крайнем
    случае — простой нарисованный виджет: приложение остаётся работоспособным.
    """
    from .avatar3d import Avatar3D

    avatar = Avatar3D(character, parent)
    if avatar.available:
        return avatar
    avatar.deleteLater()

    if assets_ready():
        live = LiveCharacter(parent)
        if live.available:
            return live
        live.deleteLater()
    from .widget import CharacterWidget

    return CharacterWidget(parent)
