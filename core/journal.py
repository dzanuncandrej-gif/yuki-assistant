"""Журнал действий с откатом.

Чем больше власти у ассистента, тем важнее возможность сказать «отмени последнее».
Каждое изменяющее действие записывается вместе со способом его отменить: громкость
помнит прежнее значение, переименование — старое имя, перезапись файла — резервную копию.

Что отменить нельзя (отправленное сообщение, закрытая программа с несохранёнными
данными) — записывается честно, без обещания отката.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

MAX_ENTRIES = 60


@dataclass
class Entry:
    action: str                      # что сделано, человеческим языком
    at: float = field(default_factory=time.time)
    undo: Callable[[], str] | None = None
    undone: bool = False

    @property
    def reversible(self) -> bool:
        return self.undo is not None and not self.undone

    @property
    def when(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.at))


_entries: deque[Entry] = deque(maxlen=MAX_ENTRIES)
_lock = threading.Lock()


def record(action: str, undo: Callable[[], str] | None = None) -> Entry:
    """Записывает действие. undo — функция, возвращающая описание того, что вернула."""
    entry = Entry(action=str(action).strip(), undo=undo)
    with _lock:
        _entries.append(entry)
    return entry


def history(limit: int = 10) -> tuple[Entry, ...]:
    with _lock:
        return tuple(list(_entries)[-limit:][::-1])


def undo_last() -> str:
    """Отменяет последнее обратимое действие."""
    with _lock:
        target = next((entry for entry in reversed(_entries) if entry.reversible), None)
    if target is None:
        return "нечего отменять"
    try:
        result = target.undo()  # type: ignore[misc]
    except Exception as err:  # noqa: BLE001 — откат не должен ронять ассистента
        return f"не удалось отменить «{target.action}»: {err}"
    target.undone = True
    return result or f"отменил: {target.action}"


def clear() -> None:
    with _lock:
        _entries.clear()


def summary(limit: int = 8) -> str:
    items = history(limit)
    if not items:
        return "действий пока не было"
    rows = []
    for entry in items:
        mark = "↩" if entry.reversible else ("✓" if not entry.undone else "×")
        rows.append(f"{entry.when} {mark} {entry.action}")
    return "; ".join(rows)
