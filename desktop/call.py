"""Окно видеосвязи: полный экран или маленькое окошко поверх всех окон.

Ядро звонка давно жило в `Assistant.start_live/stop_live` — камера, жесты,
живой взгляд на экран, итог разговора, — но окна к нему не было, и включить
звонок было нечем. Здесь это окно: страница `ui3d/call.html` плюс подача ей
кадров экрана и камеры.

Кадры не копятся: таймер смотрит на номер последнего кадра и отправляет его,
только если он новый. Не успела страница — кадр просто заменится следующим.
"""

from __future__ import annotations

import base64
import json
import threading
from typing import Any

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core import bus

from .bridge import Bridge
from .webpanel import build_view, event_json

MINI_SIZE = (360, 460)
FRAME_MS = 110   # ~9 кадров в секунду — больше страница не покажет заметно лучше


class CallLink(QObject):
    event = Signal(str)
    stats = Signal(str)
    screenFrame = Signal(str)
    cameraFrame = Signal(str)
    layout = Signal(str)

    page_ready = Signal()
    hangup_requested = Signal()
    mute_requested = Signal(bool)
    interrupt_requested = Signal()
    mini_requested = Signal()
    escape_requested = Signal()
    question = Signal(str)
    drag_requested = Signal()

    @Slot()
    def ready(self) -> None:
        self.page_ready.emit()

    @Slot()
    def hangup(self) -> None:
        self.hangup_requested.emit()

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        self.mute_requested.emit(bool(muted))

    @Slot()
    def interrupt(self) -> None:
        self.interrupt_requested.emit()

    @Slot()
    def toggleMini(self) -> None:
        self.mini_requested.emit()

    @Slot()
    def escape(self) -> None:
        self.escape_requested.emit()

    @Slot(str)
    def ask(self, text: str) -> None:
        self.question.emit(text)

    @Slot()
    def startDrag(self) -> None:
        self.drag_requested.emit()


class CallWindow(QWidget):
    """Звонок с Юки. Создаётся на один звонок и закрывается вместе с ним."""

    ended = Signal()
    mute_changed = Signal(bool)

    def __init__(self, assistant: Any, bridge: Bridge, muted: bool = False) -> None:
        super().__init__(None)
        self._assistant = assistant
        self._live = False
        self._mini = False
        self._ending = False
        self._muted = muted
        self._screen_id = -1
        self._camera_id = -1

        self.setWindowTitle("Юки — видеосвязь")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setStyleSheet("background: #03050b;")

        self.link = CallLink(self)
        self.link.page_ready.connect(self._on_ready)
        self.link.hangup_requested.connect(self.hang_up)
        self.link.mute_requested.connect(self._set_muted)
        self.link.interrupt_requested.connect(assistant.interrupt)
        self.link.mini_requested.connect(self.toggle_mini)
        self.link.escape_requested.connect(self._on_escape)
        self.link.question.connect(self._ask)
        self.link.drag_requested.connect(self._drag)

        self.view = build_view("call.html", self.link, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self._bridge = bridge
        bridge.event.connect(self._forward)

        self._frames = QTimer(self)
        self._frames.timeout.connect(self._push_frames)
        self._stats = QTimer(self)
        self._stats.timeout.connect(self._push_stats)

    # ---------------------------------------------------------------- жизненный цикл

    def start(self, screen_rect: QRect | None = None) -> None:
        geometry = screen_rect or QGuiApplication.primaryScreen().geometry()
        self.setGeometry(geometry)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._frames.start(FRAME_MS)
        self._stats.start(1000)

        def connect() -> None:
            greeting = self._assistant.start_live()
            bus.bus.log("assistant", greeting)
            self._assistant.say(greeting)

        threading.Thread(target=connect, name="jarvis-call-start", daemon=True).start()

    def hang_up(self) -> None:
        if self._ending:
            return
        self._ending = True
        self._frames.stop()
        self._stats.stop()
        try:
            self._bridge.event.disconnect(self._forward)
        except (RuntimeError, TypeError):
            pass

        assistant = self._assistant

        def finish() -> None:
            assistant.interrupt()
            summary = assistant.stop_live()
            assistant.say(summary)

        threading.Thread(target=finish, name="jarvis-call-end", daemon=True).start()
        self.ended.emit()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._ending:
            self.hang_up()
        super().closeEvent(event)

    # ---------------------------------------------------------------- раскладка

    def toggle_mini(self) -> None:
        self._set_mini(not self._mini)

    def _set_mini(self, mini: bool) -> None:
        self._mini = mini
        screen = (self.screen() or QGuiApplication.primaryScreen())
        if mini:
            area = screen.availableGeometry()
            width, height = MINI_SIZE
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
            self.showNormal()
            self.setGeometry(area.right() - width - 20, area.bottom() - height - 20, width, height)
        else:
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
            self.setGeometry(screen.geometry())
            self.showFullScreen()
        self.show()
        self.raise_()
        self.link.layout.emit("mini" if mini else "full")

    def _on_escape(self) -> None:
        # первый Esc сворачивает в угол, второй завершает звонок
        if self._mini:
            self.hang_up()
        else:
            self._set_mini(True)

    def _drag(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    # ---------------------------------------------------------------- данные

    def _on_ready(self) -> None:
        self._live = True
        self.link.layout.emit("mini" if self._mini else "full")
        self.link.event.emit(json.dumps(bus.bus.snapshot()))
        self._push_stats()

    def _forward(self, payload: dict) -> None:
        if not self._live:
            return
        text = event_json(payload)
        if text is not None:
            self.link.event.emit(text)

    def _set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._assistant.set_muted(self._muted)
        self.mute_changed.emit(self._muted)

    def _ask(self, text: str) -> None:
        threading.Thread(target=self._assistant.handle_text, args=(text,),
                         name="jarvis-call-ask", daemon=True).start()

    def _push_frames(self) -> None:
        if not self._live:
            return
        watcher = getattr(self._assistant, "_watcher", None)
        if watcher is not None and watcher.preview and watcher.preview_id != self._screen_id:
            self._screen_id = watcher.preview_id
            self.link.screenFrame.emit(base64.b64encode(watcher.preview).decode("ascii"))
        if self._mini:
            return  # в окошке кадры не видны — не гоняем их зря
        camera = getattr(self._assistant, "camera", None)
        if camera is not None and camera.preview and camera.preview_id != self._camera_id:
            self._camera_id = camera.preview_id
            self.link.cameraFrame.emit(base64.b64encode(camera.preview).decode("ascii"))

    def _push_stats(self) -> None:
        if not self._live:
            return
        data: dict[str, Any] = {"muted": self._muted}
        watcher = getattr(self._assistant, "_watcher", None)
        if watcher is not None:
            stats = watcher.stats
            data["vision"] = {
                "fps": stats.fps,
                "healthy": stats.healthy,
                # быстрое восприятие (текст и структура экрана) — главный показатель
                "analysis": f"чтение {stats.sense_ms:.0f} мс" if stats.senses else "",
            }
        camera = getattr(self._assistant, "camera", None)
        if camera is not None:
            vision = camera.vision
            data["camera"] = {
                "present": bool(vision.present),
                "people": int(vision.people),
                "identity": vision.identity if vision.known else "",
                "gesture": vision.gesture or "",
                "error": vision.error if not vision.healthy else "",
            }
        self.link.stats.emit(json.dumps(data, ensure_ascii=False))
