"""Раздел «Диалог» как командный центр: ядро из частиц и живая переписка.

Прежний диалог — полоска уровня и список карточек — остаётся запасным: его
берёт главное окно, если в сборке нет QtWebEngine.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QPainterPath, QRegion
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core import bus, voices

from .bridge import Bridge
from .webpanel import build_view, event_json, system_load


class HubLink(QObject):
    """То, что видит страница: сигналы вниз, слоты наверх."""

    event = Signal(str)
    stats = Signal(str)
    history = Signal(str)

    page_ready = Signal()
    text_submitted = Signal(str)
    mute_requested = Signal(bool)
    interrupt_requested = Signal()
    reset_requested = Signal()
    call_requested = Signal()

    @Slot()
    def ready(self) -> None:
        self.page_ready.emit()

    @Slot(str)
    def sendText(self, text: str) -> None:
        self.text_submitted.emit(text)

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        self.mute_requested.emit(bool(muted))

    @Slot()
    def interrupt(self) -> None:
        self.interrupt_requested.emit()

    @Slot()
    def reset(self) -> None:
        self.reset_requested.emit()

    @Slot()
    def startCall(self) -> None:
        self.call_requested.emit()

    @Slot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)


class HubView(QWidget):
    """Страница диалога. Снаружи — обычный виджет раздела пульта."""

    call_requested = Signal()
    mute_changed = Signal(bool)

    def __init__(self, assistant: Any, bridge: Bridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._live = False
        self._muted = False

        self.link = HubLink(self)
        self.link.page_ready.connect(self._on_ready)
        self.link.text_submitted.connect(self._on_text)
        self.link.mute_requested.connect(self.set_muted)
        self.link.interrupt_requested.connect(assistant.interrupt)
        self.link.reset_requested.connect(assistant.reset)
        self.link.call_requested.connect(self.call_requested.emit)

        self.view = build_view("hub.html", self.link, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        bridge.event.connect(self._forward)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._push_stats)
        self._stats_timer.start(1500)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # скруглённые углы — как у карточек пульта
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 20, 20)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ---------------------------------------------------------------- события

    def _on_ready(self) -> None:
        self._live = True
        items = [item for item in bus.bus.history() if item.get("type") == "message"]
        self.link.history.emit(json.dumps(items[-30:], ensure_ascii=False, default=str))
        self.link.event.emit(json.dumps(bus.bus.snapshot()))
        self._push_stats()

    def _forward(self, payload: dict) -> None:
        if not self._live:
            return
        text = event_json(payload)
        if text is not None:
            self.link.event.emit(text)

    def _on_text(self, text: str) -> None:
        threading.Thread(target=self._assistant.handle_text, args=(text,),
                         name="jarvis-hub-text", daemon=True).start()

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._assistant.set_muted(self._muted)
        self.mute_changed.emit(self._muted)
        self._push_stats()

    def _push_stats(self) -> None:
        if not self._live or not self.isVisible():
            return
        agent = getattr(self._assistant, "_agent", None)
        # только закэшированное значение: сетевая проверка в потоке интерфейса
        # при выключенной Ollama подвешивала бы окно на секунды
        online = bool(agent is not None and getattr(agent, "_online", False))
        profile = voices.get(getattr(self._assistant, "voice_key", ""))
        cpu, ram = system_load()
        self.link.stats.emit(json.dumps({
            "online": online,
            "model": (agent.model if agent is not None else None) or "—",
            "voice": profile.title if profile is not None else "—",
            "cpu": cpu, "ram": ram, "muted": self._muted,
        }, ensure_ascii=False))
