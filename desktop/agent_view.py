"""Вкладка «Агент» на веб-странице ui3d/agent.html: конвейер, план, редактор, терминал.

Страница получает события агента из шины, а наверх отдаёт команды:
создать, доработать, остановить, открыть папку, запустить. Если QtWebEngine
недоступен, главное окно берёт прежнюю страницу на виджетах.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication, QPainterPath, QRegion
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core import bus
from core.coding import checks, history

from .webpanel import build_view


class AgentLink(QObject):
    """То, что видит страница: сигналы вниз, слоты наверх."""

    event = Signal(str)
    recent = Signal(str)
    project = Signal(str)

    page_ready = Signal()
    create_requested = Signal(str)
    change_requested = Signal(str)
    stop_requested = Signal()
    load_requested = Signal(str)

    @Slot()
    def ready(self) -> None:
        self.page_ready.emit()

    @Slot(str)
    def create(self, task: str) -> None:
        self.create_requested.emit(task)

    @Slot(str)
    def change(self, task: str) -> None:
        self.change_requested.emit(task)

    @Slot()
    def stop(self) -> None:
        self.stop_requested.emit()

    @Slot(str)
    def openFolder(self, root: str) -> None:
        if root and Path(root).is_dir():
            checks.open_result(Path(root), "folder", "")

    @Slot(str)
    def openEditor(self, root: str) -> None:
        if root and Path(root).is_dir():
            checks.open_in_editor(Path(root))

    @Slot(str)
    def run(self, root: str) -> None:
        if not root or not Path(root).is_dir():
            return
        project = history.open_project(Path(root))
        if project.plan.language == "web":
            checks.open_result(project.root, "web", project.plan.entry)
        else:
            checks.launch(project.root, project.plan.entry)

    @Slot(str)
    def loadProject(self, root: str) -> None:
        self.load_requested.emit(root)

    @Slot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)


class AgentView(QWidget):
    """Страница агента — обычный виджет раздела пульта."""

    relay = Signal(str)
    project_relay = Signal(str)
    recent_relay = Signal(str)

    def __init__(self, assistant: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._live = False
        self._root: Path | None = None

        self.link = AgentLink(self)
        self.link.page_ready.connect(self._on_ready)
        self.link.create_requested.connect(lambda task: self._start(task, None))
        self.link.change_requested.connect(lambda task: self._start(task, self._root))
        self.link.stop_requested.connect(lambda: assistant.coder.cancel())
        self.link.load_requested.connect(self._load)
        # события шины приходят из потока агента — в страницу их отдаёт главный поток
        self.relay.connect(self.link.event.emit)
        self.project_relay.connect(self.link.project.emit)
        self.recent_relay.connect(self.link.recent.emit)
        bus.bus.subscribe_callback(self._on_bus)

        self.view = build_view("agent.html", self.link, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 20, 20)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _on_bus(self, payload: dict) -> None:
        if payload.get("type") != "coder":
            return
        if payload.get("event") in ("plan", "done") and payload.get("root"):
            self._root = Path(str(payload["root"]))
        if self._live:
            self.relay.emit(json.dumps(payload, ensure_ascii=False, default=str))
            if payload.get("event") == "done":
                self.recent_relay.emit(json.dumps(history.recent(), ensure_ascii=False, default=str))

    def _on_ready(self) -> None:
        self._live = True
        self.link.recent.emit(json.dumps(history.recent(), ensure_ascii=False, default=str))

    def _start(self, task: str, existing: Path | None) -> None:
        reply = self._assistant.start_code(task, existing=existing)
        bus.bus.log("system", reply)

    def _load(self, root: str) -> None:
        path = Path(root)
        if not path.is_dir():
            return

        def work() -> None:
            project = history.open_project(path)
            self._root = path
            payload = {"root": str(path), "title": project.plan.title, "plan": project.plan.as_dict(),
                       "files": project.files}
            self.project_relay.emit(json.dumps(payload, ensure_ascii=False))

        threading.Thread(target=work, daemon=True).start()
