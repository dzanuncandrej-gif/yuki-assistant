"""Отправка сообщений в десктопных мессенджерах (Telegram, WhatsApp, Discord, Slack).

Здесь нет имитации: окно ищется, чат открывается поиском, текст печатается, Enter жмётся.
Две проверки не дают ошибиться:
    1) до отправки — заголовок окна должен совпасть с именем адресата (иначе письмо ушло бы чужому);
    2) после отправки — поле ввода должно опустеть, иначе сообщение не ушло.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass

from . import apps, automation
from . import windows as win

_SENTINEL = "__jarvis_probe__"


class MessengerError(RuntimeError):
    """Мессенджер не найден, чат не открылся или сообщение не ушло."""


@dataclass(frozen=True)
class Messenger:
    key: str
    app_name: str
    window_hint: str
    search_hotkey: tuple[str, ...]
    title_shows_chat: bool  # заголовок окна показывает имя открытого чата
    search_point: tuple[int, int] | None = None  # куда кликнуть, чтобы попасть в строку поиска


MESSENGERS: dict[str, Messenger] = {
    # у Telegram Ctrl+F ищет внутри открытого чата, поэтому кликаем прямо в строку поиска слева сверху
    "telegram": Messenger("telegram", "telegram", "telegram", ("ctrl", "f"), True, (250, 50)),
    "whatsapp": Messenger("whatsapp", "whatsapp", "whatsapp", ("ctrl", "f"), False, (200, 100)),
    "discord": Messenger("discord", "discord", "discord", ("ctrl", "k"), True),
    "slack": Messenger("slack", "slack", "slack", ("ctrl", "k"), True),
}

_ALIASES = {
    "телеграм": "telegram", "телеграмм": "telegram", "телега": "telegram", "тг": "telegram",
    "вотсап": "whatsapp", "ватсап": "whatsapp", "whats app": "whatsapp",
    "дискорд": "discord", "слак": "slack",
}

# «папа» → как контакт записан в мессенджере; заполняется из config.json
_contacts: dict[str, str] = {}


def configure(contacts: dict[str, str] | None) -> None:
    if contacts:
        _contacts.update({str(k).strip().lower(): str(v) for k, v in contacts.items()})


def resolve_contact(name: str) -> str:
    """Разговорное имя превращаем в то, как контакт подписан в мессенджере."""
    return _contacts.get(name.strip().lower(), name.strip())


def _stem(word: str) -> str:
    """«папе», «папа», «папу» → «пап»: сравниваем имена без падежных окончаний."""
    base = str(word or "").strip().lower()
    for _ in range(2):
        if len(base) > 3 and base[-1] in _VOWEL_TAIL:
            base = base[:-1]
    return base


def knows(name: str) -> bool:
    """Есть ли такой контакт в настройках — по имени, по значению или по основе слова."""
    needle = str(name or "").strip().lower()
    if not needle:
        return False
    pool = set(_contacts) | {str(value).strip().lower() for value in _contacts.values()}
    if needle in pool:
        return True
    stem = _stem(needle)
    return bool(stem) and any(_stem(item) == stem for item in pool)


def resolve_messenger(name: str) -> Messenger:
    key = _ALIASES.get(name.strip().lower(), name.strip().lower())
    messenger = MESSENGERS.get(key)
    if messenger is None:
        raise MessengerError(f"мессенджер «{name}» не поддерживается")
    return messenger


def _plain(text: str) -> str:
    """Заголовки содержат невидимые метки и эмодзи — сравниваем только буквы и цифры."""
    normalized = unicodedata.normalize("NFKC", text or "")
    letters = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", letters).strip().lower()


def _title_matches(title: str, contact: str) -> bool:
    left, right = _plain(title), _plain(contact)
    if not left or not right:
        return False
    return right in left or left in right


_VOWEL_TAIL = "аеёиоуыэюяь"


def contact_variants(name: str) -> tuple[str, ...]:
    """«Алисе», «Алису», «Дмитрию» → варианты для поиска.

    Живая речь склоняет имена, а в мессенджере контакт записан в именительном падеже.
    Поиск ищет по началу слова, поэтому основа без последней буквы находит и «Алиса»,
    и «Алисе», и «Алисочка».
    """
    base = resolve_contact(name).strip()
    if not base:
        return ()

    variants = [base]
    lowered = base.lower()
    if lowered.endswith("ию") and len(base) > 4:
        variants.append(base[:-2] + "ий")
    if len(base) > 4 and lowered[-1] in _VOWEL_TAIL:
        variants.append(base[:-1])  # основа: «алисе» → «алис»
    if len(base) > 6 and lowered[-2:] in ("ом", "ым", "ой", "ей", "ам", "ах"):
        variants.append(base[:-2])
    return tuple(dict.fromkeys(item for item in variants if len(item) >= 2))


def _matches_any(title: str, queries: tuple[str, ...]) -> bool:
    return any(_title_matches(title, query) for query in queries)


def _window(messenger: Messenger, launch: bool = True, timeout_s: float = 25.0):  # noqa: ANN201
    """Окно мессенджера: ищем среди открытых, при необходимости запускаем и ждём."""
    try:
        return win.find(messenger.window_hint)
    except win.WindowError:
        pass
    if not launch:
        raise MessengerError(f"{messenger.key} не запущен")
    try:
        apps.launch(messenger.app_name)
    except apps.AppError as err:
        raise MessengerError(f"не нашёл приложение {messenger.key}: {err}") from err

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return win.find(messenger.window_hint)
        except win.WindowError:
            time.sleep(0.5)
    raise MessengerError(f"{messenger.key} не открылся за {timeout_s:.0f} секунд")


def _focus_search(messenger: Messenger, window) -> None:  # noqa: ANN001
    """Ставит курсор в строку глобального поиска: сначала кликом, иначе горячей клавишей."""
    automation.press_key("esc")
    time.sleep(0.2)
    if messenger.search_point is not None:
        left, top, right, bottom = win.rect(window)
        offset_x, offset_y = messenger.search_point
        point = (min(left + offset_x, right - 20), min(top + offset_y, bottom - 20))
        automation.mouse_click(point[0], point[1])
        time.sleep(0.35)
        # Ctrl+A недоступен, когда антивирус блокирует сочетания клавиш, — чистим забоем
        automation.press_key("backspace", times=30)
        time.sleep(0.15)
        return
    automation.press_hotkey(messenger.search_hotkey)
    time.sleep(0.6)


def _search_and_open(messenger: Messenger, target: str, window, second_try: bool = False) -> str:  # noqa: ANN001
    """Глобальный поиск по имени и открытие первого результата."""
    _focus_search(messenger, window)
    automation.type_text(target)
    time.sleep(1.8)  # результаты подгружаются с сервера
    if second_try:
        automation.press_key("down")  # первый результат мог быть не выделен
        time.sleep(0.2)
    automation.press_key("enter")
    time.sleep(1.3)
    current = win.active_window()
    return current.title if current is not None else ""


def open_chat(messenger_name: str, contact: str, timeout_s: float = 25.0) -> str:
    """Открывает переписку с контактом. Возвращает заголовок окна после открытия.

    Имя пробуется в нескольких формах: как сказали, затем основа без окончания —
    «найди Алису» находит чат «Алиса».
    """
    messenger = resolve_messenger(messenger_name)
    queries = contact_variants(contact) or (resolve_contact(contact),)
    window = _window(messenger, timeout_s=timeout_s)
    win.focus(window)
    time.sleep(0.7)

    title = ""
    for index, query in enumerate(queries):
        title = _search_and_open(messenger, query, window)
        if not messenger.title_shows_chat or _matches_any(title, queries):
            return title or query
        if index == 0:
            # первый результат мог быть не выделен — повторяем с выбором стрелкой
            title = _search_and_open(messenger, query, window, second_try=True)
            if _matches_any(title, queries):
                return title
    return title or queries[0]


def send(messenger_name: str, contact: str, message: str, timeout_s: float = 25.0) -> str:
    """Открывает чат, проверяет адресата, печатает сообщение, отправляет и подтверждает отправку."""
    if not message.strip():
        raise MessengerError("пустое сообщение")

    messenger = resolve_messenger(messenger_name)
    queries = contact_variants(contact) or (resolve_contact(contact),)
    title = open_chat(messenger_name, contact, timeout_s=timeout_s)

    if messenger.title_shows_chat and not _matches_any(title, queries):
        raise MessengerError(
            f"открылся чат «{title}», а нужен «{queries[0]}» — ничего не отправлял. "
            "Уточни, как контакт подписан в мессенджере"
        )

    automation.type_text(message)
    time.sleep(0.35)
    automation.press_key("enter")
    time.sleep(0.9)

    empty = _input_is_empty()
    if empty is False:
        raise MessengerError(f"текст остался в поле ввода — сообщение не ушло (окно «{title}»)")
    if empty is None:
        return f"{title} (проверить поле ввода не дала защита клавиатуры)"
    return title


def _input_is_empty() -> bool | None:
    """Пусто ли поле ввода. Спрашиваем у самой системы, ничего не трогая.

    None — прочитать не удалось.

    Раньше поле проверялось выделением и копированием: Ctrl+A, Ctrl+C, сравнить
    с меткой в буфере. В мессенджере это разрушительно. Когда поле уже пустое —
    а после успешной отправки оно именно пустое, — Ctrl+A выделяет не поле, а всю
    переписку. Копия истории не совпадала с меткой, проверка объявляла, что
    сообщение не ушло, и жала Delete по выделенным сообщениям.

    Работать это начало ровно тогда, когда починили SendInput: до того сочетания
    клавиш не проходили вовсе, проверка честно возвращала None, и беды не было.
    """
    from . import screen

    try:
        text = screen.focused_text()
    except Exception:  # noqa: BLE001 — дерево интерфейса недоступно
        return None
    if text is None:
        return None
    return not text.strip()
