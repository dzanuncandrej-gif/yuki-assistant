"""Свой плейлист: «Юки, включи мою любимую музыку».

Песни — обычные аудиофайлы на компьютере. Их добавляют во вкладке «Плейлист»
(кнопкой или перетаскиванием), а играет их проигрыватель внутри самой Юки, а не
браузер. Поэтому нет поиска наугад на YouTube, рекламы и чужих роликов, а
«следующая», «пауза», «что играет» работают всегда и мгновенно.

Здесь — только библиотека и голосовые команды. Сам проигрыватель живёт в
интерфейсе (Qt) и регистрируется через `attach_player`; без интерфейса
(тесты, веб-режим) команды честно отвечают, что играть нечем.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from . import config

PATH = config.ROOT / "data" / "playlist.json"
AUDIO = (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma")
_MAX_FOLDER_FILES = 2000
_NOISE = re.compile(r"\s*[\(\[](?:official|офиц|lyrics?|audio|video|клип|hd|4k|remaster\w*)[^\)\]]*[\)\]]",
                    re.IGNORECASE)
_TRACK_NUMBER = re.compile(r"^\d{1,3}[\s.\-_]+")


class PlaylistError(RuntimeError):
    """Понятная человеку причина, почему с плейлистом не вышло."""


@dataclass(frozen=True)
class Track:
    path: str
    title: str
    artist: str = ""
    added: float = field(default_factory=time.time)
    duration: int = 0       # мс; 0 — ещё не измерена
    album: str = ""
    cover: str = ""         # имя файла в data/covers
    liked: bool = False
    plays: int = 0
    tagged: bool = False    # название и исполнитель уже взяты из тегов файла

    @property
    def label(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title

    @property
    def exists(self) -> bool:
        return Path(self.path).is_file()


def describe(path: Path) -> Track:
    """Название и исполнитель из имени файла: «Artist - Song (Official Video).mp3»."""
    stem = _NOISE.sub("", path.stem).replace("_", " ").strip()
    stem = _TRACK_NUMBER.sub("", stem) or stem
    for dash in (" — ", " – ", " - "):
        if dash in stem:
            artist, title = stem.split(dash, 1)
            return Track(path=str(path), title=title.strip(), artist=artist.strip())
    return Track(path=str(path), title=stem)


# ---------------------------------------------------------------- библиотека

_lock = threading.Lock()
_FIELDS = ("path", "title", "artist", "added", "duration", "album", "cover", "liked", "plays", "tagged")


def _load() -> list[Track]:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    tracks: list[Track] = []
    for item in raw.get("tracks", []) if isinstance(raw, dict) else []:
        try:
            tracks.append(Track(**{key: item[key] for key in _FIELDS if key in item}))
        except TypeError:
            continue
    return tracks


def _save(tracks: Iterable[Track]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"tracks": [asdict(track) for track in tracks]}
    temp = PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(PATH)


def tracks() -> tuple[Track, ...]:
    with _lock:
        return tuple(_load())


def add(paths: Iterable[str | Path]) -> int:
    """Добавляет файлы и папки (со всем, что внутри). Возвращает, сколько новых песен."""
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found += sorted(item for item in path.rglob("*") if item.suffix.lower() in AUDIO)[:_MAX_FOLDER_FILES]
        elif path.is_file() and path.suffix.lower() in AUDIO:
            found.append(path)
    with _lock:
        current = _load()
        known = {str(Path(track.path).resolve()).lower() for track in current}
        fresh = []
        for path in found:
            key = str(path.resolve()).lower()
            if key not in known:
                known.add(key)
                fresh.append(describe(path.resolve()))
        if fresh:
            _save(current + fresh)
    if fresh:
        _notify()
    return len(fresh)


def update(path: str, **fields) -> Track | None:
    """Меняет поля песни (длительность, обложка, теги). Возвращает обновлённую песню."""
    from dataclasses import replace

    changed: Track | None = None
    with _lock:
        current = _load()
        for index, track in enumerate(current):
            if track.path == path:
                changed = replace(track, **{key: value for key, value in fields.items() if key in _FIELDS})
                current[index] = changed
                break
        if changed is not None:
            _save(current)
    if changed is not None:
        _notify()
    return changed


def toggle_like(path: str) -> bool:
    track = next((item for item in tracks() if item.path == path), None)
    if track is None:
        return False
    update(path, liked=not track.liked)
    return not track.liked


def count_play(path: str) -> None:
    track = next((item for item in tracks() if item.path == path), None)
    if track is not None:
        update(path, plays=track.plays + 1)


def place(path: str, index: int) -> None:
    """Ставит песню на позицию index (перетаскивание в списке)."""
    with _lock:
        current = _load()
        position = next((i for i, track in enumerate(current) if track.path == path), None)
        if position is None:
            return
        item = current.pop(position)
        current.insert(max(0, min(len(current), index)), item)
        _save(current)
    _notify()


def remove(path: str) -> None:
    with _lock:
        _save(track for track in _load() if track.path != path)
    _notify()


def move(path: str, offset: int) -> None:
    """Сдвигает песню вверх (-1) или вниз (+1) по списку."""
    with _lock:
        current = _load()
        index = next((i for i, track in enumerate(current) if track.path == path), None)
        if index is None:
            return
        target = max(0, min(len(current) - 1, index + offset))
        current.insert(target, current.pop(index))
        _save(current)
    _notify()


def find(query: str) -> int | None:
    """Номер песни, лучше всего подходящей под «включи из плейлиста Believer»."""
    words = [word for word in re.findall(r"\w+", query.lower()) if len(word) > 1]
    if not words:
        return None
    best, score = None, 0
    for index, track in enumerate(tracks()):
        label = track.label.lower()
        hits = sum(1 for word in words if word in label)
        if hits > score:
            best, score = index, hits
    return best


# ---------------------------------------------------------------- проигрыватель


class Player(Protocol):
    """То, что умеет проигрыватель интерфейса. Все методы — из любого потока."""

    repeat: str  # off | all | one

    def play(self, index: int, shuffle: bool = False) -> None: ...
    def toggle(self) -> None: ...
    def stop(self) -> None: ...
    def step(self, offset: int) -> None: ...
    def set_shuffle(self, value: bool) -> None: ...
    def current(self) -> Track | None: ...
    def playing(self) -> bool: ...
    def active(self) -> bool: ...


_player: Player | None = None
_listeners: list = []


def attach_player(player: Player | None) -> None:
    global _player
    _player = player


def on_change(callback) -> None:
    """Интерфейс перерисовывает список, когда песни добавила, например, команда голосом."""
    _listeners.append(callback)


def _notify() -> None:
    for callback in tuple(_listeners):
        try:
            callback()
        except Exception:
            continue


def active() -> bool:
    """Наш проигрыватель сейчас ведёт музыку (играет или на паузе)."""
    return _player is not None and _player.active()


def _require() -> Player:
    if _player is None:
        raise PlaylistError("проигрыватель плейлиста работает только в окне Юки")
    return _player


def play(query: str = "", shuffle: bool = False) -> str:
    """Включает плейлист целиком или песню из него. Возвращает фразу для ответа."""
    items = tracks()
    if not items:
        raise PlaylistError("плейлист пока пуст — добавь песни во вкладке «Плейлист» в меню")
    player = _require()
    index = find(query) if query else None
    if query and index is None:
        raise PlaylistError(f"в плейлисте нет ничего похожего на «{query}»")
    if index is None:
        index = random.randrange(len(items)) if shuffle else 0
    player.play(index, shuffle=shuffle)
    track = items[index]
    if query:
        return f"Включаю «{track.label}»."
    return f"Включаю твой плейлист{', вперемешку' if shuffle else ''}: «{track.label}»."


def control(action: str) -> str:
    """next / previous / play_pause / stop для своего проигрывателя."""
    player = _require()
    if action == "next":
        player.step(1)
    elif action == "previous":
        player.step(-1)
    elif action == "play_pause":
        player.toggle()
        return "продолжила" if player.playing() else "поставила на паузу"
    elif action == "stop":
        player.stop()
        return "выключила"
    track = player.current()
    return f"включила «{track.label}»" if track else "готово"


def now_playing() -> Track | None:
    return _player.current() if active() and _player is not None else None
