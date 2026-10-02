"""Вкладка «Плейлист» на веб-странице ui3d/music.html: обложка, спектр, очередь.

Страница получает состояние проигрывателя, список песен и спектр звука, а
наверх отдаёт команды. Песни можно перетащить прямо на вкладку: сам браузер
путей файлов не знает, поэтому перетаскивание принимает Qt-виджет поверх.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from core import playlist

from . import player as player_mod
from .music_probe import Prober
from .webpanel import build_view

_AUDIO_FILTER = "Музыка (" + " ".join(f"*{ext}" for ext in playlist.AUDIO) + ")"


class MusicLink(QObject):
    state = Signal(str)
    library = Signal(str)
    spectrum = Signal(str)
    progress = Signal(int, int)

    page_ready = Signal()
    command = Signal(str, str)

    @Slot()
    def ready(self) -> None:
        self.page_ready.emit()

    @Slot(str, str)
    def act(self, action: str, argument: str) -> None:
        self.command.emit(action, argument)


class MusicView(QWidget):
    library_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._player = player_mod.instance()
        self._prober = Prober(self)
        self._live = False

        self.link = MusicLink(self)
        self.link.page_ready.connect(self._on_ready)
        self.link.command.connect(self._on_command)
        self._player.changed.connect(self._push_state)
        self._player.progress.connect(self._on_progress)
        self._player.spectrum.connect(self._on_spectrum)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._push_library)
        self.library_changed.connect(self._debounce.start, Qt.ConnectionType.QueuedConnection)
        # библиотеку меняют и голосом из другого потока — перерисовка уходит в главный
        playlist.on_change(self.library_changed.emit)

        self.view = build_view("music.html", self.link, self)
        self.view.setAcceptDrops(False)  # бросок файлов ловит этот виджет, а не браузер
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        QTimer.singleShot(1500, self._prober.scan)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 20, 20)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ---------------------------------------------------------------- вниз, на страницу

    def _on_ready(self) -> None:
        self._live = True
        self._push_library()
        self._push_state()

    def _push_library(self) -> None:
        if not self._live:
            return
        items = [{"path": track.path, "title": track.title, "artist": track.artist, "album": track.album,
                  "duration": track.duration, "cover": track.cover, "liked": track.liked, "plays": track.plays,
                  "missing": not track.exists} for track in playlist.tracks()]
        self.link.library.emit(json.dumps(items, ensure_ascii=False))
        self._prober.scan()

    def _push_state(self) -> None:
        if not self._live:
            return
        track = self._player.current()
        state = {
            "playing": self._player.playing(), "shuffle": self._player.shuffle, "repeat": self._player.repeat,
            "volume": self._player.volume, "path": track.path if track else "",
            "position": self._player.position(), "duration": self._player.duration(),
        }
        self.link.state.emit(json.dumps(state, ensure_ascii=False))

    def _on_progress(self, position: int, duration: int) -> None:
        if self._live:
            self.link.progress.emit(int(position), int(duration))

    def _on_spectrum(self, bands: list) -> None:
        if self._live and self.isVisible():
            self.link.spectrum.emit(json.dumps(bands))

    # ---------------------------------------------------------------- наверх, от страницы

    def _on_command(self, action: str, argument: str) -> None:
        player = self._player
        items = playlist.tracks()
        if action == "play":
            index = next((i for i, track in enumerate(items) if track.path == argument), 0)
            player.play(index, shuffle=player.shuffle)
        elif action == "toggle":
            player.toggle()
        elif action == "next":
            player.step(1)
        elif action == "prev":
            player.step(-1)
        elif action == "seek":
            player.seek(int(float(argument or 0)))
        elif action == "volume":
            player.set_volume(float(argument or 0))
            self._push_state()
        elif action == "shuffle":
            player.set_shuffle(argument == "1")
        elif action == "repeat":
            player.set_repeat(argument)
        elif action == "like":
            playlist.toggle_like(argument)
        elif action == "remove":
            playlist.remove(argument)
        elif action == "place":
            path, _, index = argument.rpartition("|")
            playlist.place(path, int(index or 0))
        elif action == "add_files":
            files, _ = QFileDialog.getOpenFileNames(self, "Песни для плейлиста", str(Path.home() / "Music"),
                                                    _AUDIO_FILTER)
            playlist.add(files)
        elif action == "add_folder":
            folder = QFileDialog.getExistingDirectory(self, "Папка с музыкой", str(Path.home() / "Music"))
            if folder:
                playlist.add([folder])
        elif action == "reveal":
            import subprocess

            if argument and Path(argument).is_file():
                subprocess.Popen(["explorer", "/select,", str(Path(argument))])

    # ---------------------------------------------------------------- перетаскивание

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            if self._live:
                self.link.state.emit(json.dumps({"dropping": True}))

    def dragLeaveEvent(self, event) -> None:
        if self._live:
            self.link.state.emit(json.dumps({"dropping": False}))

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        added = playlist.add(paths)
        event.acceptProposedAction()
        if self._live:
            self.link.state.emit(json.dumps({"dropping": False, "added": added}))
