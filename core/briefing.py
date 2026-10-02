"""Утренний брифинг и «что мне писали?».

«Доброе утро» — Юки за пару секунд собирает дату, погоду, напоминания и
входящие Telegram и рассказывает это одним живым рассказом. Всё собирается
параллельно: погода ждёт сеть, Telegram — дерево интерфейса, и ни одно не
задерживает другое. Что не ответило вовремя, просто не попадает в рассказ.
"""

from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor, wait

from . import inbox

_GATHER_TIMEOUT_S = 8.0

# «что мне писали», «кто мне писал», «есть новые сообщения», «проверь телеграм»
INBOX = re.compile(
    r"(?:что\s+(?:мне\s+)?(?:писали|пишут|написали|прислали)|кто\s+(?:мне\s+)?(?:писал|пишет|написал)|"
    r"(?:есть|пришли|пришло)\s+(?:ли\s+)?(?:\w+\s+)?(?:нов\w+\s+)?(?:сообщени\w+|письм\w+|смс)|"
    r"проверь\s+(?:мои\s+)?(?:сообщени\w+|телеграм\w*|телегу|переписк\w+)|"
    r"(?:что|чё|че)\s+(?:нового\s+)?в\s+(?:телеграм\w*|телеге))",
    re.IGNORECASE,
)

# «доброе утро», «утренний брифинг», «что у меня сегодня», «расскажи про мой день»
BRIEFING = re.compile(
    r"^(?:юки[,\s]+)?(?:доброе\s+утро|с\s+добрым\s+утром|утренн\w+\s+(?:брифинг|сводк\w+)|брифинг|"
    r"сводк\w+\s+на\s+(?:день|сегодня)|что\s+у\s+меня\s+(?:сегодня|на\s+сегодня)|"
    r"(?:расскажи|какой)\s+(?:мне\s+)?(?:про\s+)?(?:мой|сегодняшний)\s+день)",
    re.IGNORECASE,
)


def wants_inbox(text: str) -> bool:
    return bool(INBOX.search(str(text or "")))


def wants_briefing(text: str) -> bool:
    return bool(BRIEFING.search(str(text or "").strip()))


def inbox_digest() -> str:
    """Текст о входящих для модели или понятная причина, почему его нет."""
    try:
        chats, unread = inbox.read()
    except inbox.InboxError as err:
        return f"Telegram: {err}."
    if not chats:
        return "Telegram: список чатов прочитать не удалось."
    return inbox.digest(chats, unread)


def _reminders() -> str:
    from . import reminders

    items = reminders.pending()
    if not items:
        return "Напоминаний на сегодня нет."
    today = dt.date.today()
    rows = [f"{item.when:%H:%M} — {item.text}" for item in items if item.when.date() == today]
    return "Напоминания на сегодня: " + "; ".join(rows) + "." if rows else "Напоминаний на сегодня нет."


def _weather() -> str:
    from . import web

    now = web.weather()
    try:
        later = web.forecast(days=1)
    except Exception:
        later = ""
    return f"Погода: {now}" + (f" Прогноз на день: {later}." if later else "")


def _clock() -> str:
    from .tools.clock import now_text

    return f"Сейчас {now_text()}."


def gather(with_news: bool = False) -> str:
    """Всё для брифинга одним текстом. Источники опрашиваются параллельно."""
    sources = {"clock": _clock, "weather": _weather, "reminders": _reminders, "inbox": inbox_digest}
    if with_news:
        sources["news"] = _headlines
    parts: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(fn): name for name, fn in sources.items()}
        done, _ = wait(futures, timeout=_GATHER_TIMEOUT_S)
        for future in done:
            try:
                parts[futures[future]] = future.result()
            except Exception:
                continue
    order = ("clock", "weather", "reminders", "inbox", "news")
    return "\n".join(parts[name] for name in order if parts.get(name))


def _headlines() -> str:
    from . import web

    stories = web.news(count=3)
    return "Главные новости: " + "; ".join(story.title for story in stories) + "."


INBOX_PROMPT = """Ты — Юки. Перескажи человеку голосом, что ему написали в Telegram. Ниже — последнее сообщение в каждом чате.

Как:
1. {SPEECH_RULE} На «ты», живо, как близкий друг пересказывает: «Дима зовёт на футбол, мама спрашивает, когда будешь».
2. Сначала личные сообщения от людей, потом группы. Боты и каналы — одной фразой в конце или вовсе пропусти.
3. Передавай смысл, не зачитывай дословно. Грубые слова не повторяй.
4. Коротко: до пяти предложений. Если новых сообщений нет — так и скажи одной фразой.
5. Без списков, markdown и эмодзи."""

BRIEFING_PROMPT = """Ты — Юки. Человек только что проснулся и сказал «доброе утро». Расскажи ему, что важно на сегодня, по данным ниже.

Как:
1. {SPEECH_RULE} Тепло и бодро, на «ты», как близкий друг за завтраком.
2. Порядок: короткое приветствие и день недели, погода и совет по одежде, напоминания, кто писал в Telegram, новости — если есть.
3. Только факты из данных, ничего не выдумывай. Пустое пропускай молча.
4. Шесть-восемь предложений, без списков, markdown и эмодзи. В конце — короткое пожелание на день."""
