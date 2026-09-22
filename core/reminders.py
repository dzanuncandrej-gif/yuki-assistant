"""Напоминания и таймеры: срабатывают голосом через колбэк, заданный ассистентом."""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from dataclasses import dataclass

_lock = threading.Lock()
_items: list[Reminder] = []
_speak: Callable[[str], None] | None = None


@dataclass(frozen=True)
class Reminder:
    when: dt.datetime
    text: str


def configure(speak: Callable[[str], None]) -> None:
    """Ассистент отдаёт сюда свой способ говорить."""
    global _speak
    _speak = speak


def pending() -> tuple[Reminder, ...]:
    with _lock:
        return tuple(sorted(_items, key=lambda item: item.when))


def schedule(minutes: float, text: str) -> dt.datetime:
    delay = max(1.0, float(minutes) * 60.0)
    when = dt.datetime.now() + dt.timedelta(seconds=delay)
    item = Reminder(when, text.strip() or "напоминание")

    def fire() -> None:
        with _lock:
            if item in _items:
                _items.remove(item)
        if _speak is not None:
            _speak(f"Напоминаю: {item.text}")

    with _lock:
        _items.append(item)
    timer = threading.Timer(delay, fire)
    timer.daemon = True
    timer.start()
    return when
