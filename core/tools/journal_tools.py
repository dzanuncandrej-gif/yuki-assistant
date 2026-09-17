"""Инструменты журнала: что было сделано и как это отменить."""

from __future__ import annotations

from .. import journal
from .registry import param_int, tool


@tool(
    "recent_actions",
    "Показывает, что Юки недавно сделал с системой и что из этого можно отменить.",
    {"limit": param_int("Сколько последних действий показать, 1..20")},
)
def _recent_actions(limit: int = 8) -> str:
    return journal.summary(max(1, min(20, limit)))


@tool(
    "undo_last",
    "Отменяет последнее обратимое действие: вернуть громкость, яркость, имя файла, "
    "содержимое перезаписанного файла, созданную папку.",
)
def _undo_last() -> str:
    return journal.undo_last()
