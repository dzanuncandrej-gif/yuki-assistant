"""«Что мне писали?» — сводка Telegram по списку чатов.

Telegram Desktop подписывает каждую строку списка чатов для экранных дикторов:
«Группа, 8В, Стич: вела, Получено, в 20:42» — тип, имя, пометки, последнее
сообщение, кто его отправил и время. Этого хватает, чтобы понять, кто и о чём
писал, не открывая ни одного чата и ничего не отмечая прочитанным.

«Получено» в конце — последнее сообщение пришло тебе. «Просмотрено» и «Не
просмотрено» — последнее сообщение твоё, отвечать там не нужно.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass

from . import screen
from . import windows as win

_KINDS = {"канал": "канал", "группа": "группа", "бот": "бот", "супергруппа": "группа", "чат": "чат"}
_FLAGS = re.compile(
    r"^(?:с premium|закреплено|верифицированный аккаунт|без уведомлений|в сети|был\w*\s.*|"
    r"реакции:.*|черновик.*|упоминание.*|\d+\s+непрочитанн\w+.*|онлайн)$",
    re.IGNORECASE,
)
_STATUS = {"получено": True, "просмотрено": False, "не просмотрено": False, "отправлено": False}
_TIME = re.compile(
    r"^(?:(?P<date>\d{2}\.\d{2}\.\d{4})|(?P<word>вчера|сегодня|[а-яё]+))?\s*в\s+(?P<clock>\d{1,2}:\d{2})$",
    re.IGNORECASE,
)
_UNREAD = re.compile(r"(\d+)\s+непрочитанн", re.IGNORECASE)
_SAVED = {"избранное", "saved messages"}


@dataclass(frozen=True)
class Chat:
    kind: str           # личный | группа | канал | бот
    name: str
    message: str
    incoming: bool      # последнее сообщение пришло тебе
    clock: str          # «20:42»
    days_ago: int       # 0 — сегодня, 1 — вчера, дальше — давно
    muted: bool

    @property
    def today(self) -> bool:
        return self.days_ago == 0

    def line(self) -> str:
        where = self.name if self.kind == "личный" else f"{self.kind} «{self.name}»"
        when = {0: "", 1: "вчера "}.get(self.days_ago, f"{self.days_ago} дн. назад ")
        return f"{where} ({when}{self.clock}): {self.message}"


def _days_ago(match: re.Match[str], today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    if match.group("date"):
        try:
            day = dt.datetime.strptime(match.group("date"), "%d.%m.%Y").date()
        except ValueError:
            return 99
        return max(0, (today - day).days)
    word = (match.group("word") or "").lower()
    if word in ("", "сегодня"):
        return 0
    if word == "вчера":
        return 1
    return 3  # день недели: на этой неделе, но не вчера


def parse(label: str, today: dt.date | None = None) -> Chat | None:
    """Разбирает подпись строки списка чатов. None — это не чат."""
    parts = [part.strip() for part in str(label or "").split(", ")]
    if len(parts) < 3:
        return None
    match = _TIME.match(parts[-1])
    if match is None:
        return None
    kind = "личный"
    if parts[0].lower() in _KINDS:
        kind = _KINDS[parts.pop(0).lower()]
    name = parts.pop(0)
    if name.lower() in _SAVED:
        return None  # «Избранное» — заметки самому себе, а не входящие
    parts.pop()  # время
    incoming = False
    if parts and parts[-1].lower() in _STATUS:
        incoming = _STATUS[parts.pop().lower()]
    muted = any(part.lower() == "без уведомлений" for part in parts)
    # пометки стоят сразу после имени; всё, что дальше, — текст сообщения (в нём бывают запятые)
    while parts and (_FLAGS.match(parts[0]) or parts[0].lower() in _STATUS):
        parts.pop(0)
    # реакции и счётчики Telegram дописывает уже после текста сообщения
    while parts and _FLAGS.match(parts[-1]):
        parts.pop()
    message = ", ".join(parts).strip() or "вложение"
    return Chat(kind=kind, name=name, message=message[:200], incoming=incoming,
                clock=match.group("clock"), days_ago=_days_ago(match, today), muted=muted)


def _telegram_window():
    for item in win.enumerate_windows():
        if "telegram" in item.process.lower():
            return item
    return None


class InboxError(RuntimeError):
    """Telegram не установлен или не открылся."""


def read(open_if_hidden: bool = True) -> tuple[tuple[Chat, ...], int]:
    """Чаты из списка и число непрочитанных.

    Если Telegram свёрнут в трей, окно ненадолго показывается и потом
    закрывается обратно в трей, а фокус возвращается туда, где был.
    """
    window = _telegram_window()
    previous = win.active_window()
    opened_here = False
    if window is None:
        if not open_if_hidden:
            return (), 0
        from . import outbox

        try:
            window = outbox._window(outbox.resolve_service("telegram"), timeout_s=12.0)
        except Exception as err:
            raise InboxError(f"Telegram не открылся: {err}") from err
        opened_here = True
        time.sleep(0.8)
    try:
        items = screen.elements(hwnd=int(window.hwnd), fresh=True)
    finally:
        if opened_here:
            _put_back(window, previous)
    chats: list[Chat] = []
    unread = 0
    for item in items:
        if item.role != "listitem" or "\n" in item.name:
            continue
        found = _UNREAD.search(item.name)
        if found and item.name.lower().startswith("все чаты"):
            unread = int(found.group(1))
            continue
        chat = parse(item.name)
        if chat is not None:
            chats.append(chat)
    return tuple(chats), unread


def _put_back(window, previous) -> None:
    """Telegram — обратно в трей (закрытие окна его не выключает), фокус — на место."""
    try:
        win.close(window)
    except Exception:
        try:
            win.minimize(window)
        except Exception:
            pass
    if previous is not None:
        try:
            win.focus(previous, timeout_s=1.0)
        except Exception:
            pass


def digest(chats: tuple[Chat, ...], unread: int, limit: int = 10) -> str:
    """Текст для модели: кто и что писал, сначала личные, потом группы."""
    incoming = [chat for chat in chats if chat.incoming and chat.days_ago <= 1 and chat.kind != "канал"]
    channels = [chat for chat in chats if chat.kind == "канал" and chat.days_ago <= 1]
    lines = [f"Непрочитанных чатов: {unread}."] if unread else []
    if incoming:
        lines.append("За последние сутки тебе писали (последнее сообщение в каждом чате):")
        lines += [f"- {chat.line()}" for chat in incoming[:limit]]
    else:
        lines.append("За последние сутки новых входящих сообщений в личных чатах и группах нет.")
    if channels:
        lines.append(f"Каналы с новыми постами: {', '.join(chat.name for chat in channels[:5])}.")
    return "\n".join(lines)

