"""Отправка сообщений с проверкой адресата на каждом шаге.

Отправить не тому — единственная по-настоящему необратимая ошибка помощника.
Закрытое окно открывается снова, удалённый файл лежит в корзине, а сообщение,
ушедшее чужому человеку, вернуть нельзя. Поэтому здесь всё построено вокруг одной
мысли: **между «нашла контакт» и «отправила» обязан стоять человек**.

Отправка разбита на три отдельных шага, и каждый можно остановить:

    prepare(...)  открывает мессенджер, ищет имя и возвращает, КОГО нашла
    confirm(...)  человек подтверждает, что адресат тот самый
    deliver(...)  печатает текст, отправляет и проверяет, что он ушёл

Кого именно нашли, спрашивается у дерева интерфейса Windows, а не у заголовка
окна: заголовок врёт (у Telegram он показывает прошлый чат ещё секунду после
переключения), а список результатов поиска — нет.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass

from . import apps, automation, screen
from . import windows as win

# столько ждём, пока результаты поиска подтянутся с сервера
SEARCH_WAIT_S = 1.6
OPEN_WAIT_S = 1.2


class OutboxError(RuntimeError):
    """Не удалось открыть мессенджер, найти контакт или отправить сообщение."""


@dataclass(frozen=True)
class Service:
    """Мессенджер и то, чем в нём открывается поиск."""

    key: str
    title: str
    app: str
    window_hint: str
    search_hotkey: tuple[str, ...]
    # как подписана строка поиска в дереве интерфейса
    search_words: tuple[str, ...] = ("поиск", "search")
    # где искать имя открытого собеседника
    header_words: tuple[str, ...] = ()


SERVICES: dict[str, Service] = {
    "telegram": Service(
        "telegram", "Telegram", "telegram", "telegram", ("ctrl", "f"),
        search_words=("поиск", "search"),
    ),
    "discord": Service(
        "discord", "Discord", "discord", "discord", ("ctrl", "k"),
        search_words=("поиск", "search", "искать или начать"),
    ),
    "steam": Service(
        "steam", "Steam", "steam", "steam", (),
        search_words=("поиск", "search", "найти друга"),
    ),
    "whatsapp": Service(
        "whatsapp", "WhatsApp", "whatsapp", "whatsapp", ("ctrl", "f"),
    ),
    "slack": Service(
        "slack", "Slack", "slack", "slack", ("ctrl", "k"),
    ),
}

_ALIASES = {
    "телеграм": "telegram", "телеграмм": "telegram", "телега": "telegram", "тг": "telegram",
    "дискорд": "discord", "диск": "discord",
    "стим": "steam", "стиме": "steam",
    "вотсап": "whatsapp", "ватсап": "whatsapp",
    "слак": "slack",
}


def services() -> tuple[Service, ...]:
    """Мессенджеры, которые вообще поддерживаются."""
    return tuple(SERVICES.values())


def resolve_service(name: str) -> Service:
    key = _ALIASES.get(str(name or "").strip().lower(), str(name or "").strip().lower())
    service = SERVICES.get(key)
    if service is None:
        known = ", ".join(item.title for item in SERVICES.values())
        raise OutboxError(f"не знаю мессенджер «{name}». Есть: {known}")
    return service


# ---------------------------------------------------------------- сравнение имён


def plain(text: str) -> str:
    """Только буквы и цифры в нижнем регистре: имена пестрят эмодзи и метками."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    letters = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", letters).strip().lower()


_TAIL = "аеёиоуыэюяьйъ"


# падежные окончания из двух-трёх букв: «Владимиром», «Андреем», «Наташей»
_CASE_ENDINGS = ("ами", "ями", "ому", "ему", "ого", "его", "ой", "ей", "ом", "ем", "ым", "им",
                 "ою", "ею", "ах", "ях")


def stem(word: str) -> str:
    """«Максиму», «Максимом» → «максим»: живая речь склоняет имена."""
    base = plain(word)
    for ending in _CASE_ENDINGS:
        if len(base) - len(ending) >= 4 and base.endswith(ending):
            base = base[: -len(ending)]
            break
    for _ in range(2):
        if len(base) > 3 and base[-1] in _TAIL:
            base = base[:-1]
    return base


# Уменьшительные имена. Человек говорит «напиши Ване», а в списке контактов
# записан «Иван Кузнецов» — без этой таблицы имена просто не совпадали, и
# помощник каждый раз переспрашивал даже там, где всё очевидно.
_SHORT_NAMES: dict[str, str] = {
    "ваня": "иван", "ванька": "иван", "саша": "александр", "шура": "александр",
    "сань": "александр", "дима": "дмитрий", "димон": "дмитрий", "митя": "дмитрий",
    "лёша": "алексей", "леша": "алексей", "алекс": "алексей",
    "коля": "николай", "миша": "михаил", "мишка": "михаил",
    "серёжа": "сергей", "сережа": "сергей", "серый": "сергей",
    "паша": "павел", "петя": "пётр", "гриша": "григорий", "боря": "борис",
    "толя": "анатолий", "слава": "вячеслав", "витя": "виктор", "вова": "владимир",
    "володя": "владимир", "рома": "роман", "костя": "константин", "юра": "юрий",
    "женя": "евгений", "андрюша": "андрей", "макс": "максим",
    "катя": "екатерина", "настя": "анастасия", "маша": "мария", "даша": "дарья",
    "лена": "елена", "оля": "ольга", "таня": "татьяна", "ира": "ирина",
    "света": "светлана", "наташа": "наталья", "юля": "юлия", "аня": "анна",
    "ксюша": "ксения", "лиза": "елизавета", "соня": "софия", "вика": "виктория",
}


def _full_forms(word: str) -> set[str]:
    """Имя и его полная форма: «ване» → {«ван», «иван»}.

    Сравнение по основам, а не по записи: сказали «Вове» (дательный падеж), в
    таблице «вова» — основа у обоих «вов», и полное «Владимир» находится.
    """
    base = stem(word)
    forms = {base}
    for short, long in _SHORT_NAMES.items():
        if stem(short) == base:
            forms.add(stem(long))
        # обратное направление: сказали «Иван», а подписан «Ваня»
        if stem(long) == base:
            forms.add(stem(short))
    return forms


def search_query(name: str) -> str:
    """Что печатать в поиск мессенджера.

    Живая речь склоняет имена: «напиши Владимиру». Поиск Telegram ищет по началу
    слова, и «Владимиру» не находит контакт «Владимир». Основа без окончания —
    «Владимир», «Вов», «Андр» — находит и полное имя, и ласкательные формы.
    """
    words = [stem(word) for word in plain(name).split() if word]
    return " ".join(word for word in words if len(word) >= 2) or plain(name)


# типы чатов, которыми Telegram начинает подпись элемента списка:
# «Бот, DarkspiritBOT, …», «Группа, 8В, …»
_CHAT_KINDS = frozenset({"бот", "группа", "канал", "избранное", "чат", "супергруппа",
                         "секретный чат", "bot", "group", "channel", "saved messages"})


def chat_title(label: str) -> str:
    """Имя собеседника из подписи элемента списка чатов.

    Подпись у Telegram длинная: «Лёша, Закреплено, Привет Андрюха …» — имя, затем
    отметки и начало последнего сообщения. Сравнивать с адресатом всю строку нельзя:
    «Владимир» в тексте чужого сообщения делал чат Лёши «точным совпадением», и
    письмо ушло бы не тому.
    """
    for part in str(label or "").split(","):
        clean = part.strip()
        if clean and clean.lower() not in _CHAT_KINDS:
            return clean
    return str(label or "").strip()


def similarity(said: str, found: str) -> float:
    """Насколько найденный контакт похож на названного, 0..1.

    Мера намеренно строгая. Ошибка в эту сторону стоит дороже всех остальных:
    лучше переспросить, чем отправить письмо однофамильцу.
    """
    left, right = plain(said), plain(found)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    said_words = [word for word in left.split() if word]
    found_words = [word for word in right.split() if word]
    if not said_words or not found_words:
        return 0.0

    hits = 0.0
    for word in said_words:
        forms = _full_forms(word)
        other_forms = [_full_forms(other) for other in found_words]
        if any(forms & other for other in other_forms):
            hits += 1
        elif any(len(base) >= 4 and other.startswith(base)
                 for base in forms for other in found_words):
            hits += 0.85
    score = hits / len(said_words)

    # имя целиком внутри найденного — «Максим» в «Максим Петров»
    if score < 1.0 and len(left) >= 3 and left in right:
        score = max(score, 0.9)
    return min(1.0, score)


# насколько похоже должно быть имя, чтобы отправлять без переспроса
SURE = 0.95
# ниже этого совпадение вообще не считается кандидатом
MAYBE = 0.55


# ---------------------------------------------------------------- черновик


@dataclass
class Draft:
    """Готовящееся сообщение и всё, что о нём известно."""

    service: Service
    asked: str                        # как человек назвал адресата
    text: str = ""
    found: str = ""                   # кого мы на самом деле открыли
    candidates: tuple[str, ...] = ()   # что ещё нашлось по этому имени
    confirmed: bool = False
    status: str = "новый"
    ambiguous: bool = False            # уверенно совпало больше одного разного имени

    @property
    def certain(self) -> bool:
        return bool(self.found) and not self.ambiguous and similarity(self.asked, self.found) >= SURE

    def describe(self) -> str:
        if not self.found:
            return f"{self.service.title}: контакт «{self.asked}» не найден"
        mark = "" if self.certain else " (похоже, но не точно)"
        return f"{self.service.title}: {self.found}{mark}"


_lock = threading.Lock()
_current: Draft | None = None


def current() -> Draft | None:
    """Черновик, который сейчас готовится. Им пользуются и меню, и голос."""
    with _lock:
        return _current


def cancel() -> str:
    """Отменяет подготовленное сообщение."""
    global _current
    with _lock:
        had = _current is not None
        _current = None
    return "отменила отправку" if had else "нечего отменять"


# ---------------------------------------------------------------- шаги отправки


def _window(service: Service, timeout_s: float = 25.0):
    """Окно мессенджера: найти среди открытых, иначе запустить и дождаться."""
    try:
        return win.find(service.window_hint)
    except win.WindowError:
        pass
    try:
        apps.launch(service.app)
    except apps.AppError as err:
        raise OutboxError(f"не нашла приложение {service.title}: {err}") from err

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return win.find(service.window_hint)
        except win.WindowError:
            time.sleep(0.5)
    raise OutboxError(f"{service.title} не открылся за {timeout_s:.0f} секунд")


def _focus_search(service: Service) -> bool:
    """Ставит курсор в строку поиска. Сначала по дереву, потом горячей клавишей.

    Раньше сюда был вбит щелчок по координатам «двести пятьдесят на пятьдесят».
    Он попадал в строку поиска только при одном размере окна и одной теме
    оформления: у развёрнутого окна там уже другое, и поиск начинал печататься
    в открытый чат. Дерево интерфейса знает, где строка поиска на самом деле.
    """
    for word in service.search_words:
        field = screen.find(word, role="edit", fresh=True)
        if field is not None:
            x, y = screen.click_point(field)
            automation.mouse_click(x, y)
            time.sleep(0.25)
            _clear_field()
            return True

    if service.search_hotkey:
        try:
            automation.press_hotkey(service.search_hotkey)
            time.sleep(0.5)
            _clear_field()
            return True
        except automation.ActionError:
            pass
    return False


def _clear_field() -> None:
    """Очищает поле ввода перед новым запросом."""
    try:
        automation.press_hotkey(("ctrl", "a"))
        time.sleep(0.05)
        automation.press_key("delete")
    except automation.ActionError:
        automation.press_key("backspace", times=40)
    time.sleep(0.15)


# элементы последней выдачи поиска: имя собеседника → элемент, по которому щёлкать
_last_results: dict[str, screen.Element] = {}


def _result_names(service: Service, query: str) -> tuple[str, ...]:
    """Имена в списке результатов поиска — то, из чего человек будет выбирать.

    Сравнивается только имя собеседника, а не вся подпись строки: в подписи
    есть и последнее сообщение, а в нём может встретиться чужое имя.
    """
    seen: list[str] = []
    _last_results.clear()
    for item in screen.visible_elements(fresh=True):
        if item.role not in ("listitem", "treeitem", "button", "text"):
            continue
        name = chat_title(item.name) if item.role == "listitem" else item.name.strip()
        if len(name) < 2 or len(name) > 80 or name.lower() in ("поиск", "search"):
            continue
        if similarity(query, name) < MAYBE:
            continue
        if name not in seen:
            seen.append(name)
            _last_results[name] = item
    return tuple(seen[:6])


def prepare(service_name: str, contact: str, timeout_s: float = 25.0) -> Draft:
    """Открывает мессенджер и ищет контакт. Ничего не отправляет.

    Возвращает черновик с тем, КОГО удалось найти. Решение отправлять принимает
    человек — здесь только разведка.
    """
    global _current

    service = resolve_service(service_name)
    asked = str(contact or "").strip()
    if not asked:
        raise OutboxError("не сказано, кому писать")

    window = _window(service, timeout_s=timeout_s)
    win.focus(window)
    time.sleep(0.6)
    screen.invalidate()

    if not _focus_search(service):
        raise OutboxError(
            f"не нашла строку поиска в {service.title}. Открой её сам и повтори просьбу"
        )

    automation.type_text(search_query(asked))
    time.sleep(SEARCH_WAIT_S)
    screen.invalidate()

    names = _result_names(service, asked)
    draft = Draft(service=service, asked=asked, candidates=names)

    if not names:
        draft.status = "не найден"
        with _lock:
            _current = draft
        return draft

    best = max(names, key=lambda name: similarity(asked, name))
    draft.found = best
    # «Владимир» и «Владимир Петров» оба совпадают уверенно — угадывать нельзя
    sure = {name for name in names if similarity(asked, name) >= SURE}
    draft.ambiguous = len(sure) > 1
    draft.status = "найден" if draft.certain else "нужно подтверждение"
    with _lock:
        _current = draft
    return draft


def open_found(draft: Draft) -> str:
    """Открывает переписку с найденным контактом и проверяет, что открылась она.

    Щелчок идёт по элементу списка с точным именем, а не по «первому результату»
    вслепую. Первый результат — самая частая причина письма не тому человеку:
    мессенджер ставит наверх недавние чаты, а не совпадение по имени.
    """
    target = _last_results.get(draft.found) or screen.find(draft.found, fresh=True, only_clickable=True)
    if target is None:
        # список мог быть текстовым — пробуем клавишами
        automation.press_key("enter")
    else:
        x, y = screen.click_point(target)
        automation.mouse_click(x, y)
    time.sleep(OPEN_WAIT_S)
    screen.invalidate()
    screen.wait_until_stable(timeout_s=2.0)

    opened = _opened_chat_name(draft)
    if opened:
        draft.found = opened
    draft.status = "чат открыт"
    return opened or draft.found


def _opened_chat_name(draft: Draft) -> str:
    """Имя собеседника в открытом чате — по заголовку окна и по дереву.

    Заголовок главнее: Telegram пишет в него имя открытого чата («Владимир – (2)»),
    и это единственное место, где имя относится именно к открытой переписке, а не
    к строке списка слева.
    """
    hwnd, title, _ = screen.foreground()
    header = re.sub(r"[‎‏‪-‮]", "", title or "")
    header = re.split(r"\s+[–—-]\s+", header)[0].strip()
    if header and similarity(draft.asked, header) >= MAYBE:
        return header
    best, score = "", 0.0
    for item in screen.visible_elements():
        if item.role not in ("text", "button", "listitem"):
            continue
        name = chat_title(item.name) if item.role == "listitem" else item.name.strip()
        if len(name) < 2 or len(name) > 60:
            continue
        value = similarity(draft.asked, name)
        if value > score:
            best, score = name, value
    if score >= MAYBE:
        return best
    return title.strip()


_SEARCH_FIELD = re.compile(r"^(?:поиск|search|искать|найти)", re.IGNORECASE)
_MESSAGE_FIELD = re.compile(r"^(?:сообщение|написать|message|write|напишите)", re.IGNORECASE)


def _message_field() -> screen.Element | None:
    """Поле ввода сообщения, но ни в коем случае не строка поиска.

    Запасной «самое большое поле в окне» опасен: в Telegram рядом живут поле
    поиска и поле сообщения, и текст, напечатанный в поиск, после Enter открывал
    чужой чат. Поэтому сначала поле по имени («Сообщение...»), затем любое
    редактируемое поле, кроме поиска.
    """
    screen.invalidate()
    fields = [item for item in screen.visible_elements(fresh=True)
              if item.role in ("edit", "document") and item.enabled]
    named = [item for item in fields if _MESSAGE_FIELD.match(item.name.strip())]
    if named:
        return next((item for item in named if item.focused), named[0])
    others = [item for item in fields if not _SEARCH_FIELD.match(item.name.strip())]
    if not others:
        return None
    return next((item for item in others if item.focused), max(others, key=lambda item: item.area))


def deliver(draft: Draft, text: str) -> str:
    """Печатает и отправляет сообщение. Только после подтверждения адресата."""
    global _current

    message = str(text or "").strip()
    if not message:
        raise OutboxError("пустое сообщение — нечего отправлять")
    if not draft.found:
        raise OutboxError("адресат не найден — отправлять некому")
    if not draft.confirmed and not draft.certain:
        raise OutboxError(
            f"нашла «{draft.found}», а просили «{draft.asked}». "
            "Подтверди, что это тот человек, и я отправлю"
        )

    # последняя проверка перед вводом: кто сейчас открыт на экране
    screen.invalidate()
    opened = _opened_chat_name(draft)
    if opened and similarity(draft.found, opened) < MAYBE:
        raise OutboxError(
            f"на экране открыт «{opened}», а сообщение для «{draft.found}» — не отправляю"
        )

    field = _message_field()
    if field is None:
        raise OutboxError("не вижу поля для текста сообщения — ничего не отправляла")
    if not field.focused:
        x, y = screen.click_point(field)
        automation.mouse_click(x, y)
        time.sleep(0.2)

    automation.type_text(message)
    time.sleep(0.35)
    automation.press_key("enter")
    time.sleep(0.9)
    screen.invalidate()

    draft.text = message
    draft.status = "отправлено"
    with _lock:
        _current = None
    return draft.found


def send_now(service_name: str, contact: str, text: str) -> str:
    """Весь путь разом — для случаев, когда адресат назван однозначно.

    Если найденное имя не совпадает с названным уверенно, отправка не произойдёт:
    вернётся ошибка с тем, кого нашли, и человек решит сам.
    """
    draft = prepare(service_name, contact)
    if not draft.found:
        raise OutboxError(
            f"в {draft.service.title} нет контакта «{contact}». "
            f"{'Нашла: ' + ', '.join(draft.candidates) if draft.candidates else 'Совсем ничего не нашла'}"
        )
    open_found(draft)
    return deliver(draft, text)
