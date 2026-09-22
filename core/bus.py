"""Шина событий между рабочим потоком ассистента и слушателями UI.

Два вида подписчиков: asyncio-очереди (websocket в веб-режиме) и обычные
колбэки (Qt-мост в десктопном режиме). Работает и без запущенного цикла asyncio.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any, Final

IDLE: Final = "idle"
LISTENING: Final = "listening"
THINKING: Final = "thinking"
SPEAKING: Final = "speaking"

STATES: Final = (IDLE, LISTENING, THINKING, SPEAKING)

_MAX_QUEUE = 64
_MAX_HISTORY = 40


class EventBus:
    """Потокобезопасная публикация событий в asyncio-очереди подписчиков."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._callbacks: tuple[Callable[[dict[str, Any]], None], ...] = ()
        self._lock = threading.Lock()
        self._state: str = IDLE
        self._level: float = 0.0
        self._history: tuple[dict[str, Any], ...] = ()

    # --- жизненный цикл ---

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def subscribe_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Синхронный слушатель — вызывается в потоке издателя, поэтому должен быть быстрым."""
        with self._lock:
            self._callbacks = (*self._callbacks, callback)

    def unsubscribe_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._callbacks = tuple(item for item in self._callbacks if item is not callback)

    # --- состояние ---

    @property
    def state(self) -> str:
        return self._state

    def snapshot(self) -> dict[str, Any]:
        return {"type": "state", "state": self._state, "level": self._level, "ts": time.time()}

    def history(self) -> tuple[dict[str, Any], ...]:
        """Последние реплики — UI, открытый позже старта, увидит, что уже произошло."""
        with self._lock:
            return self._history

    def set_state(self, state: str, **extra: Any) -> None:
        if state not in STATES:
            raise ValueError(f"Неизвестное состояние: {state}")
        self._state = state
        if state in (IDLE, THINKING):
            self._level = 0.0
        self.publish({"type": "state", "state": state, "level": self._level, **extra})

    def set_level(self, level: float) -> None:
        """Уровень громкости 0..1 — им UI модулирует амплитуду сферы."""
        clamped = 0.0 if level < 0.0 else (1.0 if level > 1.0 else float(level))
        self._level = clamped
        self.publish({"type": "level", "state": self._state, "level": clamped})

    def log(self, kind: str, text: str) -> None:
        """kind: user | assistant | system | error."""
        self.publish({"type": "message", "kind": kind, "text": text})

    # --- доставка ---

    def publish(self, payload: dict[str, Any]) -> None:
        event = {**payload, "ts": time.time()}
        with self._lock:
            if event.get("type") == "message":
                self._history = (*self._history, event)[-_MAX_HISTORY:]
            callbacks = self._callbacks

        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                pass

        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._fanout, event)

    def _fanout(self, event: dict[str, Any]) -> None:
        with self._lock:
            targets = tuple(self._subscribers)
        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # UI отстаёт — теряем самый старый кадр, а не текущий.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


bus = EventBus()
