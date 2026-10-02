"""«Юки, что мне ему ответить?» — варианты ответа собеседнику в открытом чате.

Юки читает переписку на экране (распознанный текст плюс снимок), понимает, что
спросил собеседник, и предлагает три коротких ответа в живом разговорном тоне.
Лучший произносит, все показывает в «Диалоге». Дальше — голосом или текстом:
«вставь», «отправь», «второй вариант», «другой». Вставляет в поле сообщения
того самого окна, где шла переписка, даже если фокус успел уйти в Юки.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field

from . import automation, screen
from . import windows as win

# «что мне ему ответить», «помоги ответить», «придумай ответ», «ответь за меня»
ASK = re.compile(
    r"(?:что\s+(?:мне\s+)?(?:ему|ей|им|тут|здесь|на\s+это)?\s*(?:ответить|написать\s+в\s+ответ)|"
    r"как\s+(?:мне\s+)?(?:ему|ей|им)?\s*ответить|помоги\s+(?:мне\s+)?ответить|придумай\s+(?:мне\s+)?ответ|"
    r"ответь\s+за\s+меня|предложи\s+ответ|варианты?\s+ответа|что\s+(?:ему|ей|им)\s+написать)",
    re.IGNORECASE,
)

_ORDINALS = {"перв": 0, "1": 0, "один": 0, "втор": 1, "2": 1, "два": 1, "трет": 2, "3": 2, "три": 2}
_PICK = re.compile(
    r"^(?P<verb>вставь|вставить|напечатай|отправь|отправить|пошли|скинь|давай|другой|ещё|еще|следующий)?"
    r"\s*(?P<which>перв\w*|втор\w*|трет\w*|[123]|один|два|три|его|это|этот|её)?\s*(?:вариант\w*|ответ\w*)?\s*"
    r"(?P<verb2>вставь|отправь)?$",
    re.IGNORECASE,
)
_TTL_S = 600.0

PROMPT = """Ты — Юки и помогаешь человеку переписываться. На экране открыт чат (мессенджер, соцсеть или почта). Ниже распознанный текст экрана и, если есть, снимок.

Найди последнее сообщение собеседника, на которое человеку нужно ответить, и придумай три варианта ответа от лица человека.

Правила:
— Пиши так, как сам человек пишет в этом чате (смотри его прошлые сообщения): коротко, по-русски, на «ты», если собеседник на «ты», без официоза и канцелярита.
— Варианты разные по смыслу или тону: например, согласие, уточнение, вежливый отказ — что уместно.
— Каждый вариант — одна-две фразы, без кавычек, без эмодзи, если собеседник сам их не ставит.
— Ничего не выдумывай про факты, которых нет в переписке: если нужно знать время или место — предложи уточнить.

Ответ — строго JSON без пояснений:
{"who": "имя собеседника или пусто", "asked": "что он спросил, коротко", "options": ["вариант 1", "вариант 2", "вариант 3"]}"""


@dataclass
class Suggestion:
    hwnd: int
    title: str
    who: str
    asked: str
    options: list[str]
    index: int = 0
    at: float = field(default_factory=time.monotonic)

    @property
    def current(self) -> str:
        return self.options[self.index] if self.options else ""


_lock = threading.Lock()
_pending: Suggestion | None = None


def wants_help(text: str) -> bool:
    return bool(ASK.search(str(text or "")))


def pending() -> Suggestion | None:
    with _lock:
        if _pending is not None and time.monotonic() - _pending.at > _TTL_S:
            return None
        return _pending


def parse_options(raw: str) -> tuple[str, str, list[str]]:
    """Достаёт JSON из ответа модели, даже если вокруг него что-то написано."""
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise ValueError("модель не вернула варианты")
    data = json.loads(match.group(0))
    options = [str(item).strip().strip("«»\"'") for item in data.get("options") or [] if str(item).strip()]
    if not options:
        raise ValueError("пустые варианты")
    return str(data.get("who") or "").strip(), str(data.get("asked") or "").strip(), options[:3]


_OWN = ("python", "pythonw", "qtwebengineprocess")


def target_window():
    """Окно переписки: активное, а если активна сама Юки — ближайшее под ней."""
    active = win.active_window()
    if active is not None and not active.process.lower().startswith(_OWN):
        return active
    for item in win.enumerate_windows():
        if item.title and not item.process.lower().startswith(_OWN):
            return item
    return active


def read_chat(window) -> tuple[str, bytes | None]:
    """Текст и снимок только окна переписки — не всего экрана с Юки поверх."""
    from . import ocr

    region = win.rect(window) if window is not None else None
    text = ""
    image: bytes | None = None
    try:
        text = ocr.read_screen(region).compact(2600)
    except Exception:
        pass
    try:
        image = screen.capture(region).encode(side=1280, quality=82)
    except Exception:
        image = None
    title = f"Окно: «{window.title}» ({window.process}).\n" if window is not None else ""
    return title + "Текст переписки (распознан): " + text, image


def remember(options: list[str], who: str, asked: str, window=None) -> Suggestion:
    """Запоминает варианты и окно, куда их потом вставлять."""
    global _pending
    active = window or target_window()
    suggestion = Suggestion(
        hwnd=int(active.hwnd) if active is not None else 0,
        title=active.title if active is not None else "",
        who=who, asked=asked, options=options,
    )
    with _lock:
        _pending = suggestion
    return suggestion


def as_report(suggestion: Suggestion) -> str:
    """Карточка с вариантами для «Диалога»."""
    head = f"**{suggestion.who}** спрашивает: {suggestion.asked}" if suggestion.who else f"Вопрос: {suggestion.asked}"
    rows = "\n".join(f"{index}. {text}" for index, text in enumerate(suggestion.options, start=1))
    return (f"## Варианты ответа\n{head}\n\n{rows}\n\n"
            "> Скажи «вставь», «отправь», «второй вариант» или «другой» — я сделаю.")


def handle_pick(text: str) -> str | None:
    """«вставь», «отправь второй», «другой вариант». None — фраза не про варианты."""
    suggestion = pending()
    if suggestion is None:
        return None
    clean = str(text or "").strip(" .!?,").lower()
    match = _PICK.match(clean)
    if not match or not clean:
        return None
    verb = (match.group("verb") or match.group("verb2") or "").lower()
    which = (match.group("which") or "").lower()
    if not verb and not which:
        return None
    if verb in ("другой", "ещё", "еще", "следующий") and not which:
        suggestion.index = (suggestion.index + 1) % len(suggestion.options)
        return f"Можно так: {suggestion.current}"
    for stem, index in _ORDINALS.items():
        if which.startswith(stem) and index < len(suggestion.options):
            suggestion.index = index
            break
    if verb.startswith(("вставь", "вставить", "напечатай")):
        insert(suggestion, send=False)
        return "Вставила, проверь и отправь."
    if verb.startswith(("отправь", "отправить", "пошли", "скинь")):
        insert(suggestion, send=True)
        return f"Отправила: {suggestion.current}"
    return f"Вариант {suggestion.index + 1}: {suggestion.current.rstrip('.!')}. Сказать «вставь» или «отправь»?"


def insert(suggestion: Suggestion, send: bool = False) -> None:
    """Печатает вариант в поле сообщения того окна, где шла переписка."""
    global _pending
    target = next((item for item in win.enumerate_windows() if int(item.hwnd) == suggestion.hwnd), None)
    if target is None:
        raise automation.ActionError("окно с перепиской закрыто — открой его и попроси ещё раз")
    win.focus(target)
    time.sleep(0.25)
    screen.invalidate()
    field = _message_field()
    if field is not None and not field.focused:
        x, y = screen.click_point(field)
        automation.mouse_click(x, y)
        time.sleep(0.15)
    automation.type_text(suggestion.current)
    if send:
        time.sleep(0.12)
        automation.press_key("enter")
        with _lock:
            _pending = None


def _message_field():
    """Поле ввода сообщения, как у отправки через Telegram, но для любого мессенджера."""
    try:
        from . import outbox

        return outbox._message_field()
    except Exception:
        return None
