"""Трёхмерный персонаж как обычный виджет панели компаньона.

Снаружи выглядит так же, как рисованный `CharacterWidget` и старый GPU-риг: те
же методы, тот же сигнал `clicked`. Внутри — встроенный в приложение движок
отображения, в котором крутится сцена three.js со скелетом на 274 кости и 148
мимическими шейпами. Никакого браузера и сети: страница читается по внутренней
схеме `jarvis:`, а разговор с питоном идёт по QWebChannel.

Если движок или собранная модель недоступны, виджет честно сообщает об этом
через `available`, и панель берёт прежнего рисованного персонажа.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .. import webassets
from ..theme import STATE_COLORS

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    ENGINE_READY = True
except ImportError:  # pragma: no cover — сборка без QtWebEngine
    ENGINE_READY = False


class Link(QObject):
    """Объект, который видит страница. Сигналы вниз, слоты — наверх."""

    stateChanged = Signal(str)
    levelChanged = Signal(float)
    visemeChanged = Signal(str)
    emotionRequested = Signal(str, float)
    gestureRequested = Signal(str)
    reactRequested = Signal(str)
    settingsChanged = Signal(str)
    characterChanged = Signal(str)
    pointerMoved = Signal(float, float, bool)

    ready = Signal(dict)
    clicked = Signal()
    dragStarted = Signal()
    failed = Signal(str)

    @Slot("QVariant")
    def onReady(self, info: Any) -> None:
        self.ready.emit(dict(info) if isinstance(info, dict) else {})

    @Slot()
    def onClick(self) -> None:
        self.clicked.emit()

    @Slot()
    def onDragStart(self) -> None:
        self.dragStarted.emit()

    @Slot(str)
    def onError(self, text: str) -> None:
        self.failed.emit(text)


class Avatar3D(QWidget):
    """Живой трёхмерный персонаж с интерфейсом рисованного виджета."""

    clicked = Signal()
    drag_requested = Signal()
    load_failed = Signal(str)

    def __init__(self, character: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.available = False
        self._pending: list[tuple[str, tuple[Any, ...]]] = []
        self._live = False
        self._state = "idle"
        self._follow = True
        self._character = character or self._first_character()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(220, 360)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if not ENGINE_READY or not webassets.available() or self._character is None:
            return

        self.link = Link(self)
        self.link.ready.connect(self._on_ready)
        self.link.clicked.connect(self.clicked.emit)
        self.link.dragStarted.connect(self.drag_requested.emit)
        self.link.failed.connect(self.load_failed.emit)

        self.view = self._build_view()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        # курсор нужен и когда мышь вне окна: персонаж провожает её взглядом
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._push_cursor)
        self._cursor_timer.start(60)

        self.available = True

    # ---------------------------------------------------------------- сборка

    @staticmethod
    def _first_character() -> str | None:
        items = webassets.characters()
        return str(items[0]["id"]) if items else None

    def _build_view(self) -> QWebEngineView:
        view = QWebEngineView(self)
        view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        view.setStyleSheet("background: transparent;")

        # свой профиль: страница персонажа не делит кэш и куки ни с чем другим
        profile = QWebEngineProfile("jarvis-companion", view)
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self._handler = webassets.AssetHandler(parent=profile)
        profile.installUrlSchemeHandler(webassets.SCHEME, self._handler)

        page = QWebEnginePage(profile, view)
        page.setBackgroundColor(Qt.GlobalColor.transparent)
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, False)

        channel = QWebChannel(page)
        channel.registerObject("jarvis", self.link)
        page.setWebChannel(channel)

        view.setPage(page)
        view.load(webassets.url("companion.html", f"character={self._character}"))
        return view

    # ---------------------------------------------------------------- очередь

    def _send(self, signal: str, *args: Any) -> None:
        """До готовности страницы команды копятся: иначе первые события теряются."""
        if not self.available:
            return
        if not self._live:
            self._pending = [item for item in self._pending if item[0] != signal][-32:]
            self._pending.append((signal, args))
            return
        getattr(self.link, signal).emit(*args)

    def _on_ready(self, info: dict) -> None:
        self._live = True
        for signal, args in self._pending:
            getattr(self.link, signal).emit(*args)
        self._pending.clear()

    def _push_cursor(self) -> None:
        if not self._live or not self._follow or not self.isVisible():
            return
        cursor = QCursor.pos()
        centre = self.mapToGlobal(self.rect().center())
        span = max(360.0, float(self.width()) * 1.6)
        self.link.pointerMoved.emit((cursor.x() - centre.x()) / span,
                                    (cursor.y() - centre.y()) / span, True)

    # ---------------------------------------------------------------- API панели

    def set_state(self, state: str) -> None:
        self._state = state
        self._send("stateChanged", state)

    def set_level(self, level: float) -> None:
        self._send("levelChanged", float(level))

    def set_viseme(self, data: Mapping[str, float]) -> None:
        self._send("visemeChanged", json.dumps(dict(data)))

    def play_emotion(self, key: str, seconds: float = 2.4) -> None:
        self._send("emotionRequested", key, float(seconds))

    def play_gesture(self, name: str) -> None:
        """Отдельный жест: кивок, наклон головы, пожатие плечами."""
        self._send("gestureRequested", name)

    def react(self, kind: str) -> None:
        """Крупная реакция: greet, success, error, question."""
        self._send("reactRequested", kind)

    def set_character(self, character: str) -> None:
        if character == self._character:
            return
        self._character = character
        self._send("characterChanged", character)

    def apply(self, settings: Mapping[str, Any]) -> None:
        self._follow = bool(settings.get("follow_cursor", True))
        self._send("settingsChanged", json.dumps(dict(settings)))

    # --- совместимость с прежним персонажем панели ---

    def set_skin(self, key: str) -> None:
        """Внешность задаёт выбранная модель, ключ голоса на неё не влияет."""

    def set_scale(self, scale: float) -> None:
        self.apply({"scale": max(0.5, min(1.6, float(scale)))})

    def set_follow_cursor(self, enabled: bool) -> None:
        self._follow = bool(enabled)
        self.apply({"follow_cursor": bool(enabled)})

    def set_idle_motion(self, enabled: bool) -> None:
        self.apply({"idle_motion": bool(enabled)})

    def set_lip_sync(self, enabled: bool) -> None:
        self.apply({"lip_sync": bool(enabled)})

    def set_accent(self, color: QColor) -> None:
        self.apply({"accent": QColor(color).name()})

    @property
    def emotion_title(self) -> str:
        return {"idle": "спокойна", "listening": "слушает",
                "thinking": "думает", "speaking": "говорит"}.get(self._state, "спокойна")

    def accent_for(self, state: str) -> QColor:
        return QColor(STATE_COLORS.get(state, STATE_COLORS["idle"]))
