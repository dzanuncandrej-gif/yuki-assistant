"""Инструменты долгой памяти: запомнить, вспомнить, забыть."""

from __future__ import annotations

from .. import memory
from .registry import param_int, param_str, tool


@tool(
    "remember",
    "Запоминает факт о пользователе надолго: предпочтения, имена, пароли от привычек, "
    "рабочие детали, планы. Используй, когда человек говорит «запомни» или сообщает "
    "что-то, что пригодится в следующих разговорах.",
    {
        "fact": param_str("Что запомнить, одной фразой"),
        "tag": param_str("Тема: работа, дом, техника, люди, привычки"),
    },
    ["fact"],
)
def _remember(fact: str, tag: str = "общее") -> str:
    saved = memory.remember(fact, tag)
    return f"запомнил ({saved.tag}): {saved.text}"


@tool(
    "recall",
    "Ищет в памяти, что известно по теме. Вызывай, когда вопрос касается прошлых "
    "разговоров, привычек или личных данных пользователя.",
    {"query": param_str("О чём вспомнить"), "limit": param_int("Сколько записей, 1..10")},
)
def _recall(query: str = "", limit: int = 5) -> str:
    hits = memory.recall(query, limit=max(1, min(10, limit)))
    if not hits:
        return "в памяти ничего нет по этой теме"
    return "; ".join(f"{fact.text} [{fact.tag}, {fact.at}]" for fact in hits)


@tool(
    "forget",
    "Удаляет из памяти записи по теме.",
    {"query": param_str("Что забыть")},
    ["query"],
    confirm=True,
)
def _forget(query: str) -> str:
    removed = memory.forget(query)
    return f"удалено записей: {removed}" if removed else "подходящих записей не нашлось"
