"""Фоновое чтение песен плейлиста: длительность, теги и обложка из самого файла.

Отдельный беззвучный QMediaPlayer по очереди открывает новые песни и
забирает то, что записано в файле: название, исполнителя, альбом и
встроенную обложку. Обложка сохраняется в data/covers уменьшенной копией.
Каждая песня читается один раз — потом у неё стоит отметка `tagged`.
"""

from __future__ import annotations

import hashlib
from collections import deque

from PySide6.QtCore import QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaMetaData, QMediaPlayer

from core import playlist

from .webassets import COVERS

_TIMEOUT_MS = 4000
_COVER_SIDE = 360


def cover_name(path: str) -> str:
    return hashlib.sha1(path.lower().encode("utf-8")).hexdigest()[:16] + ".jpg"


class Prober(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._queue: deque[str] = deque()
        self._current: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._skip)

    def scan(self) -> None:
        """Ставит в очередь все песни, которые ещё не читались."""
        waiting = set(self._queue) | ({self._current} if self._current else set())
        for track in playlist.tracks():
            if not track.tagged and track.exists and track.path not in waiting:
                self._queue.append(track.path)
        if self._current is None:
            QTimer.singleShot(0, self._next)

    def _next(self) -> None:
        if not self._queue:
            self._current = None
            self._player.setSource(QUrl())
            return
        self._current = self._queue.popleft()
        self._timer.start(_TIMEOUT_MS)
        self._player.setSource(QUrl.fromLocalFile(self._current))

    def _skip(self) -> None:
        if self._current:
            playlist.update(self._current, tagged=True)
        self._next()

    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._current is None:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._timer.stop()
            self._skip()
        elif status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._timer.stop()
            self._read(self._current)
            self._next()

    def _read(self, path: str) -> None:
        meta = self._player.metaData()
        fields: dict = {"tagged": True, "duration": int(self._player.duration())}
        title = (meta.stringValue(QMediaMetaData.Key.Title) or "").strip()
        artist = (meta.stringValue(QMediaMetaData.Key.ContributingArtist)
                  or meta.stringValue(QMediaMetaData.Key.AlbumArtist) or "").strip()
        album = (meta.stringValue(QMediaMetaData.Key.AlbumTitle) or "").strip()
        # тегам верим, только если они осмысленные: «Track 01» хуже имени файла
        if title and not title.lower().startswith(("track", "дорожка")):
            fields["title"] = title
            if artist:
                fields["artist"] = artist
        if album:
            fields["album"] = album
        for key in (QMediaMetaData.Key.ThumbnailImage, QMediaMetaData.Key.CoverArtImage):
            image = meta.value(key)
            if isinstance(image, QImage) and not image.isNull():
                COVERS.mkdir(parents=True, exist_ok=True)
                name = cover_name(path)
                scaled = image.scaled(_COVER_SIDE, _COVER_SIDE, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
                if scaled.save(str(COVERS / name), "JPG", 88):
                    fields["cover"] = name
                break
        playlist.update(path, **fields)
