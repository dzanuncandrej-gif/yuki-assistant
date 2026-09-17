"""Время и дата берутся у системы прямо в момент вызова — модель их не выдумывает."""

from __future__ import annotations

import datetime as dt
import time

from .registry import param_int, param_str, tool

MONTHS = (
    "января февраля марта апреля мая июня июля "
    "августа сентября октября ноября декабря"
).split()

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def now_text() -> str:
    now = dt.datetime.now().astimezone()
    return (
        f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year} года, "
        f"{now.strftime('%H:%M')} ({now.tzname() or 'местное время'})"
    )


@tool("get_time", "Текущее точное время и дата на компьютере пользователя. Вызывай всегда, когда спрашивают про время, дату, день недели или 'сегодня'.")
def _get_time() -> str:
    return now_text()


@tool(
    "wait",
    "Пауза перед следующим шагом: подождать загрузки окна, страницы или приложения.",
    {"seconds": param_int("Сколько секунд ждать, 1..30")},
    ["seconds"],
)
def _wait(seconds: int) -> str:
    delay = max(0.2, min(30.0, float(seconds)))
    time.sleep(delay)
    return f"подождал {delay:.0f} секунд"


@tool(
    "timer",
    "Ставит напоминание через N минут: по истечении Юки скажет текст вслух.",
    {
        "minutes": param_int("Через сколько минут напомнить"),
        "text": param_str("Что сказать при срабатывании"),
    },
    ["minutes", "text"],
)
def _timer(minutes: int, text: str) -> str:
    from .. import reminders

    when = reminders.schedule(float(minutes), text)
    return f"напоминание поставлено на {when.strftime('%H:%M')}"


@tool("list_timers", "Показывает поставленные напоминания и таймеры.")
def _list_timers() -> str:
    from .. import reminders

    items = reminders.pending()
    if not items:
        return "напоминаний нет"
    return "; ".join(f"{item.when.strftime('%H:%M')} — {item.text}" for item in items)
