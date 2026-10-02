"""Проигрыватель плейлиста внутри Юки (QtMultimedia, без браузера и новых библиотек).

Команды приходят из любого потока — голосовой ассистент живёт в своём, — поэтому
каждая команда превращается в сигнал и выполняется уже в главном потоке Qt.
Пока Юки говорит или слушает, музыка приглушается, чтобы её было слышно.

Спектр звука считается из аудиобуфера проигрывателя (QAudioBufferOutput +
numpy) и отдаётся странице плейлиста — по нему пляшут полосы и ядро.
"""

from __future__ import annotations

import random
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioBuffer, QAudioBufferOutput, QAudioFormat, QAudioOutput, QMediaPlayer

from core import bus, playlist

_DUCK = 0.25          # громкость музыки, пока Юки говорит, — доля от обычной
_DEFAULT_VOLUME = 0.6
_BANDS = 32
_SPECTRUM_EVERY = 1 / 30
REPEATS = ("all", "one", "off")


class MusicPlayer(QObject):
    """Реализует `playlist.Player`. Создаётся один раз в главном потоке."""

    changed = Signal()                  # сменилась песня или состояние
    progress = Signal(int, int)         # позиция и длительность, мс
    spectrum = Signal(list)             # 32 полосы 0..1, ~30 раз в секунду
    _command = Signal(str, object)
    _ducking = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._volume = _DEFAULT_VOLUME
        self._ducked = False
        self._order: list[str] = []
        self._cursor = -1
        self._shuffle = False
        self._track: playlist.Track | None = None
        self._playing = False
        self.repeat = "all"
        self._audio.setVolume(self._volume)
        self._bands = np.zeros(_BANDS, dtype=np.float32)
        self._last_spectrum = 0.0
        self._buffers = QAudioBufferOutput(self)
        self._player.setAudioBufferOutput(self._buffers)
        self._buffers.audioBufferReceived.connect(self._on_buffer)

        queued = Qt.ConnectionType.QueuedConnection
        self._command.connect(self._handle, queued)
        self._ducking.connect(self._apply_duck, queued)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.positionChanged.connect(lambda pos: self.progress.emit(pos, self._player.duration()))
        self._player.errorOccurred.connect(self._on_error)
        bus.bus.subscribe_callback(self._on_bus)
        playlist.attach_player(self)

    # ---------------------------------------------------------------- playlist.Player (любой поток)

    def play(self, index: int, shuffle: bool = False) -> None:
        self._command.emit("play", (index, shuffle))

    def toggle(self) -> None:
        # состояние меняется сразу: голосовой ответ «поставила на паузу» читает его следом
        self._playing = not self._playing if self._track is not None else False
        self._command.emit("toggle", None)

    def stop(self) -> None:
        self._playing = False
        self._command.emit("stop", None)

    def step(self, offset: int) -> None:
        self._command.emit("step", offset)

    def set_shuffle(self, value: bool) -> None:
        self._command.emit("shuffle", bool(value))

    def set_repeat(self, mode: str) -> None:
        self.repeat = mode if mode in REPEATS else "all"
        self.changed.emit()

    def position(self) -> int:
        return int(self._player.position())

    def duration(self) -> int:
        return int(self._player.duration())

    def current(self) -> playlist.Track | None:
        return self._track

    def playing(self) -> bool:
        return self._playing

    def active(self) -> bool:
        return self._track is not None

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @property
    def volume(self) -> float:
        return self._volume

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, value))
        self._apply_duck(self._ducked)

    def seek(self, position_ms: int) -> None:
        self._player.setPosition(max(0, int(position_ms)))

    # ---------------------------------------------------------------- главный поток

    def _handle(self, action: str, argument: object) -> None:
        if action == "play":
            index, shuffle = argument  # type: ignore[misc]
            self._start(int(index), bool(shuffle))
        elif action == "toggle":
            if self._track is None:
                self._start(0, self._shuffle)
            elif self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
        elif action == "stop":
            self._player.stop()
            self._track = None
            self._publish()
        elif action == "step":
            self._advance(int(argument))  # type: ignore[arg-type]
        elif action == "shuffle":
            self._shuffle = bool(argument)
            if self._track is not None:
                self._build_order(self._track.path)
            self.changed.emit()

    def _build_order(self, first: str | None) -> None:
        paths = [track.path for track in playlist.tracks()]
        if self._shuffle:
            random.shuffle(paths)
        if first in paths:
            paths.remove(first)
            paths.insert(0, first)
        self._order = paths
        self._cursor = 0

    def _start(self, index: int, shuffle: bool) -> None:
        items = playlist.tracks()
        if not items:
            return
        self._shuffle = shuffle
        self._build_order(items[max(0, min(index, len(items) - 1))].path)
        self._load_current()

    def _advance(self, offset: int) -> None:
        if not self._order:
            self._start(0, self._shuffle)
            return
        # назад в первые три секунды песни — предыдущая, позже — эта же сначала
        if offset < 0 and self._player.position() > 3000:
            self._player.setPosition(0)
            return
        self._cursor = (self._cursor + offset) % len(self._order)
        self._load_current()

    def _load_current(self, attempts: int = 0) -> None:
        if not self._order or attempts >= len(self._order):
            self._track = None
            self._playing = False
            self._publish()
            return
        library = {track.path: track for track in playlist.tracks()}
        track = library.get(self._order[self._cursor])
        if track is None or not track.exists:
            # файл удалили или переместили — молча идём к следующему
            self._cursor = (self._cursor + 1) % len(self._order)
            self._load_current(attempts + 1)
            return
        self._track = track
        self._playing = True
        self._player.setSource(QUrl.fromLocalFile(track.path))
        self._player.play()
        playlist.count_play(track.path)
        self._publish()

    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._advance(1)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat == "one":
                self._player.setPosition(0)
                self._player.play()
            elif self.repeat == "off" and self._cursor >= len(self._order) - 1:
                self._playing = False
                self._publish()
            else:
                self._advance(1)
        elif status == QMediaPlayer.MediaStatus.LoadedMedia and self._track and not self._track.duration:
            # длительность становится известна, только когда файл открыт
            playlist.update(self._track.path, duration=int(self._player.duration()))

    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self._playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._publish()

    def _on_error(self, error, text: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            bus.bus.log("error", f"плейлист: {text or 'файл не воспроизводится'}")

    def _publish(self) -> None:
        self.changed.emit()
        track = self._track
        bus.bus.publish({
            "type": "music",
            "title": track.title if track else "",
            "artist": track.artist if track else "",
            "playing": self._playing and track is not None,
        })
        if not self._playing:
            self._bands[:] = 0
            self.spectrum.emit([0.0] * _BANDS)

    # ---------------------------------------------------------------- спектр

    def _on_buffer(self, buffer: QAudioBuffer) -> None:
        """Полосы спектра из кусочка звука: БПФ, логарифмические полосы, мягкое затухание."""
        now = time.monotonic()
        if now - self._last_spectrum < _SPECTRUM_EVERY or not self._playing:
            return
        self._last_spectrum = now
        fmt = buffer.format()
        dtype = {QAudioFormat.SampleFormat.Float: np.float32, QAudioFormat.SampleFormat.Int16: np.int16,
                 QAudioFormat.SampleFormat.Int32: np.int32}.get(fmt.sampleFormat())
        if dtype is None:
            return
        data = np.frombuffer(bytes(buffer.constData()), dtype=dtype).astype(np.float32)
        if dtype is np.int16:
            data /= 32768.0
        elif dtype is np.int32:
            data /= 2147483648.0
        channels = max(1, fmt.channelCount())
        if data.size < 256 * channels:
            return
        mono = data[: data.size // channels * channels].reshape(-1, channels).mean(axis=1)[-2048:]
        magnitude = np.abs(np.fft.rfft(mono * np.hanning(mono.size)))
        edges = np.unique(np.geomspace(2, magnitude.size - 1, _BANDS + 1).astype(int))
        bands = np.array([magnitude[a:b].mean() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])],
                         dtype=np.float32)
        bands = np.clip(np.log10(1 + bands * 4) / 1.6, 0, 1)
        if bands.size < _BANDS:
            bands = np.pad(bands, (0, _BANDS - bands.size))
        # быстрое нарастание, плавный спад — полосы не дёргаются
        self._bands = np.where(bands > self._bands, bands, self._bands * 0.82 + bands * 0.18)
        self.spectrum.emit([round(float(value), 3) for value in self._bands])

    # ---------------------------------------------------------------- приглушение под голос

    def _on_bus(self, event: dict) -> None:
        if event.get("type") == "state":
            self._ducking.emit(event.get("state") in (bus.SPEAKING, bus.LISTENING))

    def _apply_duck(self, ducked: bool) -> None:
        self._ducked = ducked
        self._audio.setVolume(self._volume * (_DUCK if ducked else 1.0))


_instance: MusicPlayer | None = None


def instance() -> MusicPlayer:
    """Единственный проигрыватель приложения; создаётся в главном потоке."""
    global _instance
    if _instance is None:
        _instance = MusicPlayer()
    return _instance
