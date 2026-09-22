"""Глаза: то, что сейчас на экране — окна, элементы интерфейса, текст, изменения.

Два источника, и это принципиально.

**Дерево интерфейса Windows (UI Automation)** — точный источник. Он отдаёт имя,
роль и настоящие координаты каждой кнопки, пункта меню и поля ввода примерно за
сотую долю секунды и без видеокарты. По нему и только по нему выполняются щелчки.

**Модель зрения** — источник смысла. Она понимает картинку, игру, диаграмму, читает
то, чего нет в дереве. Но координаты её выдумка: на проверке она указала на кнопку
«Закрыть» мимо на полсотни пикселей, а на уменьшенном снимке — вообще за пределы
экрана. Поэтому её ответы никогда не превращаются в клики.

Отсюда правило, на котором держится весь модуль: **видеть — можно чем угодно,
нажимать — только по координатам из дерева интерфейса.** Если элемента в дереве
нет, честнее сказать «не вижу такой кнопки», чем ткнуть наугад.
"""

from __future__ import annotations

import io
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

_local = threading.local()

# Сколько дерево интерфейса считается свежим. Оно строится за сотые доли секунды,
# поэтому срок короткий: лучше перечитать, чем щёлкнуть по вчерашней кнопке.
TREE_TTL_S = 0.7

# Роли, по которым вообще имеет смысл щёлкать
CLICKABLE = frozenset({
    "button", "menuitem", "listitem", "tabitem", "checkbox", "radiobutton",
    "hyperlink", "splitbutton", "combobox", "treeitem", "menu", "custom",
})

# Роли, в которые можно печатать
EDITABLE = frozenset({"edit", "document", "combobox"})


class ScreenError(RuntimeError):
    """Экран не читается: нет доступа к дереву интерфейса или к снимку."""


# ---------------------------------------------------------------- снимок экрана


@dataclass(frozen=True)
class Shot:
    """Снимок области экрана вместе с моментом съёмки.

    Момент важен не меньше картинки: по нему видно, не устарел ли кадр. Половина
    ошибок «она кликает не туда» — это решение, принятое по снимку, сделанному до
    того, как окно перерисовалось.
    """

    image: Any                      # PIL.Image
    at: float                       # time.monotonic() в момент захвата
    region: tuple[int, int, int, int]  # left, top, right, bottom на экране

    @property
    def age(self) -> float:
        return time.monotonic() - self.at

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def encode(self, side: int = 1280, quality: int = 85) -> bytes:
        """JPEG для модели зрения.

        Тысяча двести восемьдесят точек по длинной стороне — не случайность.
        На семистах шестидесяти восьми, как было раньше, подписи кнопок и текст
        в окне превращаются в кашу, и модель начинает их домысливать. Кодирование
        большего кадра стоит две миллисекунды — за такую цену лучше видеть.
        """
        picture = self.image
        if max(picture.size) > side:
            picture = picture.copy()
            picture.thumbnail((side, side))
        buffer = io.BytesIO()
        picture.convert("RGB").save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()


def _grabber():
    """Свой захватчик на поток: mss нельзя делить между потоками."""
    grabber = getattr(_local, "mss", None)
    if grabber is None:
        import mss

        grabber = mss.mss()
        _local.mss = grabber
    return grabber


def capture(region: tuple[int, int, int, int] | None = None) -> Shot:
    """Снимок всего экрана или его части. Около двадцати миллисекунд."""
    from PIL import Image

    grabber = _grabber()
    monitor = grabber.monitors[1]
    if region is None:
        box = {"left": monitor["left"], "top": monitor["top"],
               "width": monitor["width"], "height": monitor["height"]}
        bounds = (monitor["left"], monitor["top"],
                  monitor["left"] + monitor["width"], monitor["top"] + monitor["height"])
    else:
        left, top, right, bottom = region
        left, top = max(left, monitor["left"]), max(top, monitor["top"])
        right = min(right, monitor["left"] + monitor["width"])
        bottom = min(bottom, monitor["top"] + monitor["height"])
        if right - left < 8 or bottom - top < 8:
            raise ScreenError("область слишком мала для снимка")
        box = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        bounds = (left, top, right, bottom)

    raw = grabber.grab(box)
    image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    return Shot(image=image, at=time.monotonic(), region=bounds)


# ---------------------------------------------------------------- дерево интерфейса


@dataclass(frozen=True)
class Element:
    """Элемент интерфейса с настоящими координатами на экране."""

    name: str
    role: str
    left: int
    top: int
    right: int
    bottom: int
    enabled: bool = True
    focused: bool = False
    value: str = ""
    depth: int = 0

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def clickable(self) -> bool:
        return self.enabled and self.role in CLICKABLE and self.area > 0

    def label(self) -> str:
        mark = "" if self.enabled else " (недоступно)"
        return f"{self.name} [{self.role}]{mark}"


# Числовые коды ролей UI Automation в человеческие имена. Полный список велик,
# здесь только то, с чем реально имеет дело голосовой помощник.
_ROLES: dict[int, str] = {
    50000: "button", 50001: "calendar", 50002: "checkbox", 50003: "combobox",
    50004: "edit", 50005: "hyperlink", 50006: "image", 50007: "listitem",
    50008: "list", 50009: "menu", 50010: "menubar", 50011: "menuitem",
    50012: "progressbar", 50013: "radiobutton", 50014: "scrollbar", 50015: "slider",
    50016: "spinner", 50017: "statusbar", 50018: "tab", 50019: "tabitem",
    50020: "text", 50021: "toolbar", 50022: "tooltip", 50023: "tree",
    50024: "treeitem", 50025: "custom", 50026: "group", 50027: "thumb",
    50028: "datagrid", 50029: "dataitem", 50030: "document", 50031: "splitbutton",
    50032: "window", 50033: "pane", 50034: "header", 50035: "headeritem",
    50036: "table", 50037: "titlebar", 50038: "separator",
}


def _uia():
    """Клиент UI Automation для текущего потока.

    COM живёт по потокам: объект, созданный в одном, в другом молча не работает.
    Голосовой цикл, поток камеры и поток наблюдателя экрана ходят сюда каждый
    сам по себе, поэтому клиент и создаётся на поток.
    """
    client = getattr(_local, "uia", None)
    if client is not None:
        return client
    try:
        import comtypes
        import comtypes.client

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            pass  # поток уже в другой модели — это не мешает
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as schema

        client = comtypes.client.CreateObject(
            schema.CUIAutomation, interface=schema.IUIAutomation
        )
    except Exception as err:
        raise ScreenError(f"дерево интерфейса недоступно: {str(err)[:120]}") from err
    _local.uia = client
    _local.uia_schema = schema
    return client


def _schema():
    _uia()
    return _local.uia_schema


@dataclass
class _Cached:
    hwnd: int
    at: float
    elements: tuple[Element, ...]


_cache_lock = threading.Lock()
_cache: dict[int, _Cached] = {}
_generation = 0


def invalidate() -> None:
    """Сообщает, что экран изменился и дерево нужно перечитать.

    Вызывается после каждого действия — щелчка, ввода текста, переключения окна.
    Без этого следующий взгляд возвращал бы состояние до действия, и помощник
    делал бы второй шаг по устаревшей картине: щёлкал по кнопке, которой уже нет,
    или повторял то, что уже сделал.
    """
    global _generation
    with _cache_lock:
        _generation += 1
        _cache.clear()
    forget_looks()


def foreground() -> tuple[int, str, str]:
    """Активное окно: указатель, заголовок, имя процесса."""
    from . import windows as win

    info = win.active_window()
    if info is None:
        return 0, "", ""
    return info.hwnd, info.title, info.process


# Роли, которые вообще интересны голосовому помощнику. Список нужен не для
# красоты: запрос всего дерева подряд у приложения на Chromium возвращает больше
# полутысячи узлов и стоит полсекунды, а отбор по ролям выполняется на стороне
# приложения и оставляет сотню — сорок пять миллисекунд. Разница между «помощник
# смотрит на экран мгновенно» и «помощник заметно подвисает на каждом взгляде».
_WANTED_TYPES: tuple[int, ...] = (
    50000,  # button
    50002,  # checkbox
    50003,  # combobox
    50004,  # edit
    50005,  # hyperlink
    50007,  # listitem
    50009,  # menu
    50011,  # menuitem
    50013,  # radiobutton
    50019,  # tabitem
    50020,  # text
    50024,  # treeitem
    50029,  # dataitem
    50031,  # splitbutton
)


def _cached(node, prop: str, default: Any = None) -> Any:
    """Свойство из кэша. Не всякий элемент отдаёт каждое — молча берём умолчание."""
    try:
        return getattr(node, prop)
    except Exception:
        return default


def _condition(client, schema):
    """Условие отбора: нужные роли и только то, что сейчас видно на экране."""
    wanted = None
    for kind in _WANTED_TYPES:
        single = client.CreatePropertyCondition(schema.UIA_ControlTypePropertyId, kind)
        wanted = single if wanted is None else client.CreateOrCondition(wanted, single)
    onscreen = client.CreatePropertyCondition(schema.UIA_IsOffscreenPropertyId, False)
    return client.CreateAndCondition(wanted, onscreen)


def _walk(client, schema, root, limit: int) -> tuple[Element, ...]:
    """Видимые органы управления одним запросом с кэшем свойств.

    Именно `FindAllBuildCache` делает чтение быстрым: без него каждое обращение к
    имени или прямоугольнику — отдельный вызов между процессами, и обход окна
    занимает секунды вместо сотой доли.
    """
    request = client.CreateCacheRequest()
    for prop in (
        schema.UIA_NamePropertyId,
        schema.UIA_ControlTypePropertyId,
        schema.UIA_BoundingRectanglePropertyId,
        schema.UIA_IsEnabledPropertyId,
        schema.UIA_HasKeyboardFocusPropertyId,
    ):
        request.AddProperty(prop)
    request.TreeScope = schema.TreeScope_Subtree

    found = root.FindAllBuildCache(
        schema.TreeScope_Subtree, _condition(client, schema), request
    )
    items: list[Element] = []
    for index in range(min(found.Length, limit)):
        try:
            node = found.GetElement(index)
            rect = _cached(node, "CachedBoundingRectangle")
            if rect is None:
                continue
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if width <= 0 or height <= 0:
                continue
            name = (_cached(node, "CachedName", "") or "").strip()
            role = _ROLES.get(_cached(node, "CachedControlType", 0), "custom")
            if not name and role not in EDITABLE:
                continue  # безымянная рамка ничего не говорит ни человеку, ни модели
            items.append(
                Element(
                    name=name,
                    role=role,
                    left=int(rect.left), top=int(rect.top),
                    right=int(rect.right), bottom=int(rect.bottom),
                    enabled=bool(_cached(node, "CachedIsEnabled", True)),
                    focused=bool(_cached(node, "CachedHasKeyboardFocus", False)),
                )
            )
        except Exception:
            continue
    return tuple(items)


MAX_ELEMENTS = 400


# Классы всплывающих окон Windows: раскрытое меню, выпадающий список, подсказка.
# Раскрытое меню — не часть окна программы, а отдельное окно поверх всех. Пока их
# не читали, «нажми Файл» открывало меню, а следующий взгляд его не находил:
# помощник считал, что ничего не произошло, и жал ещё раз.
_POPUP_CLASSES = frozenset({
    "#32768",            # системное меню
    "#32770",            # диалоговое окно
    "ComboLBox",         # раскрытый выпадающий список
    "DropDown",
    "Windows.UI.Core.CoreWindow",
    "Xaml_WindowedPopupClass",
})


def popups() -> tuple[int, ...]:
    """Указатели видимых всплывающих окон: меню, списки, диалоги."""
    try:
        import win32gui
    except ImportError:
        return ()

    found: list[int] = []

    def visit(hwnd: int, _: Any) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            name = win32gui.GetClassName(hwnd)
            if name in _POPUP_CLASSES:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                if right - left > 8 and bottom - top > 8 and left > -20000:
                    found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(visit, None)
    except Exception:
        return ()
    return tuple(found)


def visible_elements(fresh: bool = False) -> tuple[Element, ...]:
    """Всё, что сейчас видно: активное окно плюс раскрытые меню и диалоги поверх него."""
    items = list(elements(fresh=fresh))
    active = foreground()[0]
    for hwnd in popups():
        if hwnd == active:
            continue
        try:
            items.extend(elements(hwnd=hwnd, fresh=fresh))
        except ScreenError:
            continue
    return tuple(items)


def elements(hwnd: int | None = None, fresh: bool = False) -> tuple[Element, ...]:
    """Элементы активного окна (или указанного). Кэшируются на доли секунды."""
    if hwnd is None:
        hwnd = foreground()[0]
    if not hwnd:
        return ()

    if not fresh:
        with _cache_lock:
            hit = _cache.get(hwnd)
            if hit is not None and (time.monotonic() - hit.at) < TREE_TTL_S:
                return hit.elements

    client = _uia()
    schema = _schema()
    try:
        root = client.ElementFromHandle(hwnd)
    except Exception as err:
        raise ScreenError(f"окно недоступно для чтения: {str(err)[:100]}") from err
    items = _walk(client, schema, root, MAX_ELEMENTS)

    with _cache_lock:
        _cache[hwnd] = _Cached(hwnd=hwnd, at=time.monotonic(), elements=items)
    return items


def windows_list() -> tuple[Element, ...]:
    """Окна верхнего уровня — что вообще открыто на рабочем столе.

    Список берётся у самой системы, а не из дерева UI Automation: у корня дерева
    в детях лежат рабочий стол и служебные панели, а настоящие окна приложений
    там не всегда видны — список выходил пустым при полудюжине открытых программ.
    """
    from . import windows as win

    active = foreground()[0]
    items: list[Element] = []
    for info in win.enumerate_windows():
        try:
            left, top, right, bottom = win.rect(info)
        except Exception:
            continue
        if right - left <= 0 or bottom - top <= 0:
            continue
        # свёрнутое окно Windows уводит далеко за пределы экрана; на экране его нет
        if left < -20000 or top < -20000:
            continue
        items.append(Element(
            name=info.title or info.process, role="window",
            left=left, top=top, right=right, bottom=bottom,
            focused=info.hwnd == active,
        ))
    return tuple(items)


# ---------------------------------------------------------------- поиск элемента


_WORD = re.compile(r"[\w]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [word.lower() for word in _WORD.findall(text or "")]


# Подписи на экране почти никогда не совпадают с тем, как о них говорят.
# Русский калькулятор Windows называет цифры словами — «Семь», «Плюс», «Равно», —
# и просьба «нажми 7» не находила ничего, хотя кнопка была прямо на виду.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "0": ("нуль", "ноль"), "1": ("один",), "2": ("два",), "3": ("три",),
    "4": ("четыре",), "5": ("пять",), "6": ("шесть",), "7": ("семь",),
    "8": ("восемь",), "9": ("девять",),
    "+": ("плюс", "сложить", "добавление"),
    "-": ("минус", "вычесть", "вычитание"),
    "*": ("умножить", "умножить на", "умножение"),
    "/": ("разделить", "разделить на", "деление"),
    "=": ("равно", "равняется", "результат"),
    ".": ("десятичный разделитель", "запятая", "точка"),
    ",": ("десятичный разделитель", "запятая", "точка"),
    "%": ("процент",),
    "ok": ("ок", "хорошо", "принять"),
    "ок": ("ok",),
    "отмена": ("cancel", "отменить"),
    "закрыть": ("close", "закрой"),
    "сохранить": ("save", "сохрани"),
    "открыть": ("open", "открой"),
    "отправить": ("send", "отправь"),
    "удалить": ("delete", "remove", "удали"),
    "назад": ("back", "вернуться"),
    "далее": ("next", "вперёд", "продолжить"),
    "поиск": ("search", "найти"),
    "настройки": ("settings", "параметры", "options"),
    "да": ("yes",), "нет": ("no",),
}


def _variants(query: str) -> tuple[str, ...]:
    """Как ещё может называться то, что попросили нажать."""
    base = (query or "").strip().lower()
    if not base:
        return ()
    found = [base, *(_SYNONYMS.get(base, ()))]
    # обратное направление: сказали «семь», а на кнопке написано «7»
    for key, words in _SYNONYMS.items():
        if base in words and key not in found:
            found.append(key)
    # «нажми цифру 7» — вытащим из фразы то, что похоже на подпись
    if len(base) > 2:
        for token in _tokens(base):
            if token in _SYNONYMS and token not in found:
                found.append(token)
                found.extend(word for word in _SYNONYMS[token] if word not in found)
    return tuple(dict.fromkeys(found))


def _coverage(needle: str, name: str) -> float:
    """Какую долю подписи занимает найденный кусок.

    Совпадение «сохранить» внутри «Сохранить» — это попадание. То же слово внутри
    «Сохранить копию проекта в облачном хранилище» — уже совсем другая кнопка.
    Без учёта доли короткий запрос уверенно находил длинные посторонние подписи.
    """
    if not name:
        return 0.0
    return min(1.0, max(0.25, len(needle) / len(name)))


def _score(query: str, item: Element) -> float:
    """Насколько элемент похож на то, что назвал человек.

    Точное совпадение важнее вхождения, вхождение важнее общих слов. Кнопка,
    в которую можно ткнуть, важнее подписи рядом с ней: у надписи и кнопки
    «Отправить» одинаковое имя, но нажимается только вторая.
    """
    name = item.name.lower()
    if not name:
        return 0.0
    options = _variants(query)
    if not options:
        return 0.0

    words = set(_tokens(name))
    base = 0.0
    for index, needle in enumerate(options):
        # синоним чуть слабее того, что назвали дословно
        penalty = 0.0 if index == 0 else 0.05
        if name == needle:
            value = 1.0
        elif needle in words:
            value = 0.9  # отдельное слово подписи, а не случайные буквы внутри
        elif len(needle) <= 2:
            # Короткий запрос обязан совпасть целиком или отдельным словом.
            # Иначе «7» находилось внутри «+57 -0» и щелчок уходил в чужую кнопку
            # на другом конце экрана — самый неприятный вид промаха.
            continue
        elif name.startswith(needle) or name.endswith(needle):
            value = 0.85 * _coverage(needle, name)
        elif needle in name:
            value = 0.7 * _coverage(needle, name)
        else:
            wanted = set(_tokens(needle))
            if not wanted:
                continue
            shared = wanted & words
            if not shared:
                continue
            value = 0.55 * (len(shared) / len(wanted))
        base = max(base, value - penalty)
    if base <= 0.0:
        return 0.0

    if item.role in CLICKABLE:
        base += 0.12
    if item.role == "text":
        base -= 0.10  # подпись, а не орган управления
    if not item.enabled:
        base -= 0.25
    if item.focused:
        base += 0.04
    # огромные области (панели, документы) редко бывают тем, что назвали
    if item.area > 700_000:
        base -= 0.15
    return base


def find(query: str, role: str | None = None, hwnd: int | None = None,
         fresh: bool = False, only_clickable: bool = False) -> Element | None:
    """Лучший подходящий элемент или None. Никаких догадок о координатах."""
    items = elements(hwnd=hwnd, fresh=fresh) if hwnd else visible_elements(fresh=fresh)
    if role:
        items = tuple(item for item in items if item.role == role)
    if only_clickable:
        # Абзац текста, в котором случайно встретилось нужное слово, — не кнопка.
        # Без этого «нажми 7» находило строку документа со словом «7» и щёлкало
        # посреди чужого текста.
        items = tuple(item for item in items if item.clickable)
    best, best_score = None, 0.0
    for item in items:
        value = _score(query, item)
        if value > best_score:
            best, best_score = item, value
    return best if best_score >= 0.5 else None


def matches(query: str, limit: int = 5, hwnd: int | None = None) -> tuple[Element, ...]:
    """Несколько подходящих элементов — чтобы переспросить, если их много."""
    pool = elements(hwnd=hwnd) if hwnd else visible_elements()
    scored = [(_score(query, item), item) for item in pool]
    good = [item for value, item in sorted(scored, key=lambda pair: -pair[0]) if value >= 0.5]
    return tuple(good[:limit])


def clickables(hwnd: int | None = None, limit: int = 40) -> tuple[Element, ...]:
    """Во что сейчас можно ткнуть. Крупные и видимые — первыми."""
    pool = elements(hwnd=hwnd) if hwnd else visible_elements()
    items = [item for item in pool if item.clickable and item.name]
    items.sort(key=lambda item: (item.top, item.left))
    return tuple(items[:limit])


def screen_text(hwnd: int | None = None, limit: int = 2000) -> str:
    """Весь текст, который система знает об окне.

    Это не распознавание картинки, а настоящие строки интерфейса: заголовки,
    подписи, содержимое полей. Ошибиться в них нельзя — в отличие от модели,
    которая читает буквы с картинки и иногда додумывает.
    """
    seen: list[str] = []
    total = 0
    for item in (elements(hwnd=hwnd) if hwnd else visible_elements()):
        piece = item.name.strip()
        if not piece or piece in seen:
            continue
        seen.append(piece)
        total += len(piece)
        if total >= limit:
            break
    return " · ".join(seen)


# ---------------------------------------------------------------- изменения на экране


@dataclass(frozen=True)
class Scene:
    """Состояние экрана, собранное без видеокарты. Основа всех решений."""

    title: str
    process: str
    focused: str          # элемент под клавиатурным фокусом
    controls: tuple[Element, ...]
    texts: tuple[str, ...]
    dialog: str = ""      # заголовок модального окна или сообщения об ошибке
    at: float = field(default_factory=time.monotonic)

    @property
    def age(self) -> float:
        return time.monotonic() - self.at

    def summary(self, limit: int = 12) -> str:
        """Короткое описание для языковой модели: окно, фокус, органы управления."""
        parts = [f"Окно: «{self.title}» ({self.process})."]
        if self.dialog:
            parts.append(f"Диалог: {self.dialog}.")
        if self.focused:
            parts.append(f"Фокус: {self.focused}.")
        names = [item.name for item in self.controls if item.name][:limit]
        if names:
            parts.append("Можно нажать: " + ", ".join(names) + ".")
        if self.texts:
            parts.append("Текст: " + " · ".join(self.texts[:8]))
        return " ".join(parts)


# слова, по которым узнаётся окно с ошибкой или вопросом
_TROUBLE = re.compile(
    r"(?:ошибк\w*|сбой|не\s+удалось|не\s+удаётся|отказано|недоступ\w+|неверн\w+|"
    r"предупрежд\w+|внимание|подтверд\w+|вы\s+уверены|сохранить\s+изменения|"
    r"error|failed|failure|cannot|denied|warning|are\s+you\s+sure|unsaved)",
    re.IGNORECASE,
)


def scene(fresh: bool = False) -> Scene:
    """Что сейчас на экране — точно, мгновенно и без модели.

    Это главный источник для решений. Модель зрения подключается только там, где
    структуры недостаточно: картинки, игры, содержимое холста.
    """
    hwnd, title, process = foreground()
    try:
        items = visible_elements(fresh=fresh)
    except ScreenError:
        items = ()

    focused = next((item.label() for item in items if item.focused), "")
    controls = tuple(item for item in items if item.clickable)
    texts = tuple(
        item.name for item in items
        if item.role in ("text", "document") and len(item.name) > 1
    )

    return Scene(title=title, process=process, focused=focused,
                 controls=controls, texts=texts,
                 dialog=_dialog_of(hwnd, title, items, controls))


# кнопки, которыми закрывается окно вопроса или сообщения
_DIALOG_BUTTONS = frozenset({
    "ок", "ok", "отмена", "cancel", "да", "нет", "yes", "no", "закрыть", "close",
    "сохранить", "save", "не сохранять", "don't save", "продолжить", "continue",
    "повторить", "retry", "пропустить", "skip", "применить", "apply",
})


def _dialog_of(hwnd: int, title: str, items: Sequence[Element],
               controls: Sequence[Element]) -> str:
    """Окно вопроса или сообщения об ошибке — если оно действительно есть.

    Проверка нарочно структурная. По одним словам-приметам она срабатывала на
    чём попало: слово «error» в открытом документе объявлялось диалогом, и
    помощник докладывал о несуществующей ошибке. Настоящий диалог узнаётся иначе —
    это маленькое окно с парой кнопок вида «ОК» и «Отмена».
    """
    if not hwnd:
        return ""
    try:
        import win32gui

        window_class = win32gui.GetClassName(hwnd)
    except Exception:
        window_class = ""

    named = [item for item in controls if item.name]
    has_dialog_button = any(item.name.strip().lower() in _DIALOG_BUTTONS for item in named)
    # #32770 — системный класс диалоговых окон Windows
    looks_modal = window_class == "#32770" or (has_dialog_button and len(named) <= 8)
    if not looks_modal and not _TROUBLE.search(title or ""):
        return ""

    # текст сообщения: самая длинная короткая надпись в окне
    lines = [item.name.strip() for item in items
             if item.role == "text" and 2 < len(item.name.strip()) <= 200]
    message = max(lines, key=len) if lines else ""
    head = title.strip()
    return f"{head}: {message}"[:220] if message else head[:220]


# ---------------------------------------------------------------- модель зрения


# Разбор кадра моделью стоит секунды и вытесняет языковую модель из видеопамяти,
# поэтому один и тот же вопрос по неизменившемуся экрану отвечается из памяти.
_look_lock = threading.Lock()
_look_cache: dict[str, tuple[bytes, float, str]] = {}
LOOK_TTL_S = 25.0
# насколько должен измениться экран, чтобы прошлый ответ считался устаревшим
LOOK_CHANGE = 0.06


def look(question: str, url: str, region: tuple[int, int, int, int] | None = None,
         timeout_s: float = 60.0) -> str:
    """Смысловой разбор кадра моделью зрения. С кэшем по неизменившемуся экрану.

    Снимается активное окно, а не весь рабочий стол: на кадре без лишнего вокруг
    модель разбирает мелкий текст заметно вернее, а сам кадр легче.
    """
    from . import vision

    if region is None:
        hwnd = foreground()[0]
        if hwnd:
            from . import windows as win

            try:
                left, top, right, bottom = win.rect(win.active_window())  # type: ignore[arg-type]
                if right - left > 200 and bottom - top > 150:
                    region = (left, top, right, bottom)
            except Exception:
                region = None

    shot = capture(region)
    mark = fingerprint(shot)
    key = (question or "").strip().lower()

    with _look_lock:
        hit = _look_cache.get(key)
        if hit is not None:
            seen, when, answer = hit
            if (time.monotonic() - when) < LOOK_TTL_S and difference(seen, mark) < LOOK_CHANGE:
                return answer

    model = vision.available_model(url)
    if model is None:
        raise ScreenError("модель зрения не установлена: ollama pull qwen2.5vl:3b")
    answer = vision.describe(
        shot.encode(), url, model, vision._prompt_for(model, question),
        timeout_s=timeout_s, num_predict=200, keep_alive=vision.LIVE_KEEP_ALIVE,
    )
    answer = vision.to_russian(answer, url)

    with _look_lock:
        _look_cache[key] = (mark, time.monotonic(), answer)
        if len(_look_cache) > 24:
            oldest = min(_look_cache.items(), key=lambda pair: pair[1][1])[0]
            _look_cache.pop(oldest, None)
    return answer


def forget_looks() -> None:
    """Сбрасывает кэш разбора: экран изменился так, что прошлые ответы не годятся."""
    with _look_lock:
        _look_cache.clear()


# ---------------------------------------------------------------- действия по элементу


def _click_scale() -> float:
    """Во сколько раз координаты для мыши отличаются от координат дерева.

    Дерево интерфейса всегда отдаёт настоящие пиксели экрана. Мышь же управляется
    из процесса, который при масштабе больше ста процентов может видеть экран
    уменьшенным. Тогда кнопка из дерева лежит, скажем, на 1500, а мыши нужно
    сказать 1000 — и щелчок без пересчёта уходит мимо.

    На обычном стопроцентном масштабе множитель равен единице и ничего не меняет.
    """
    try:
        import ctypes

        logical = ctypes.windll.user32.GetSystemMetrics(0)
    except Exception:
        return 1.0
    try:
        physical = _grabber().monitors[1]["width"]
    except Exception:
        return 1.0
    if not logical or not physical:
        return 1.0
    ratio = logical / physical
    return ratio if abs(ratio - 1.0) > 0.02 else 1.0


def click_point(item: Element) -> tuple[int, int]:
    """Точка, по которой мыши следует щёлкнуть, чтобы попасть в этот элемент."""
    x, y = item.center
    scale = _click_scale()
    return (round(x * scale), round(y * scale)) if scale != 1.0 else (x, y)


def click(query: str, role: str | None = None, double: bool = False) -> str:
    """Нажимает на элемент по имени. Координаты берутся из дерева, не из догадок.

    Если такого элемента нет — честная ошибка со списком того, что есть рядом.
    Ткнуть «примерно туда» нельзя: промах по чужой кнопке хуже, чем отказ.
    """
    from . import automation

    target = find(query, role=role, fresh=True, only_clickable=True)
    if target is None:
        near = ", ".join(item.name for item in clickables()[:10]) or "ничего не видно"
        raise ScreenError(f"не вижу кнопки «{query}». Сейчас доступно: {near}")
    if not target.enabled:
        raise ScreenError(f"«{target.name}» сейчас недоступна")

    x, y = click_point(target)
    automation.mouse_click(x, y, clicks=2 if double else 1)
    invalidate()  # экран изменился — всё, что мы о нём знали, устарело
    return f"нажала «{target.name}» ({target.role}) в точке {x},{y}"


def focused_text() -> str | None:
    """Текст поля ввода под курсором. None — прочитать не удалось.

    Читается напрямую у системы, без буфера обмена. Прежняя проверка «пусто ли
    поле» выделяла его через Ctrl+A и копировала: в мессенджере, где поле уже
    пустое, Ctrl+A выделяет всю переписку, копирует её, и проверка решает, что
    сообщение не ушло. А следом жмёт Delete — по выделенным сообщениям.
    """
    try:
        client = _uia()
        schema = _schema()
        node = client.GetFocusedElement()
    except Exception:
        return None
    for pattern_id, attribute in (
        (schema.UIA_ValuePatternId, "CurrentValue"),
        (schema.UIA_TextPatternId, None),
    ):
        try:
            pattern = node.GetCurrentPattern(pattern_id)
            if pattern is None:
                continue
            if attribute is not None:
                value = getattr(pattern.QueryInterface(
                    schema.IUIAutomationValuePattern), attribute)
                return str(value or "")
            document = pattern.QueryInterface(schema.IUIAutomationTextPattern)
            return str(document.DocumentRange.GetText(4096) or "")
        except Exception:
            continue
    return None


def editable(query: str = "") -> Element | None:
    """Поле ввода по имени, а если имени нет — то, в которое сейчас пишут.

    Область текста в Блокноте, редакторе или мессенджере часто вовсе без имени:
    в дереве это безымянный `document`. По названию такое не найти, поэтому
    запасной путь — поле под фокусом, а если и его нет, самое большое поле ввода
    в окне. Именно туда человек и имеет в виду печатать.
    """
    named = find(query, fresh=True) if query.strip() else None
    if named is not None and named.role in EDITABLE:
        return named

    fields = [item for item in visible_elements() if item.role in EDITABLE and item.enabled]
    if not fields:
        return named  # ничего похожего на поле — вернём то, что нашли по имени
    focused = next((item for item in fields if item.focused), None)
    if focused is not None:
        return focused
    return max(fields, key=lambda item: item.area)


def focus_element(query: str) -> Element:
    """Ставит курсор в поле ввода по имени и возвращает само поле."""
    from . import automation

    target = editable(query)
    if target is None:
        raise ScreenError(f"не вижу поля «{query}» и ни одного поля ввода в окне")
    if not target.focused:
        x, y = click_point(target)
        automation.mouse_click(x, y)
        invalidate()
        time.sleep(0.15)
    return target


def wait_for(query: str, timeout_s: float = 8.0, gone: bool = False) -> Element | None:
    """Ждёт появления (или исчезновения) элемента. Так проверяется результат действия.

    Без этого многошаговая задача разваливается: помощник печатает в окно, которое
    ещё не открылось, и считает, что всё получилось.
    """
    deadline = time.monotonic() + max(0.5, timeout_s)
    while time.monotonic() < deadline:
        invalidate()
        found = find(query, fresh=True)
        if gone and found is None:
            return None
        if not gone and found is not None:
            return found
        time.sleep(0.25)
    if gone:
        raise ScreenError(f"«{query}» всё ещё на экране")
    return None


def wait_until_stable(timeout_s: float = 4.0, quiet_s: float = 0.45) -> bool:
    """Ждёт, пока экран перестанет меняться: анимация, загрузка, перерисовка.

    Снимок, сделанный посреди анимации, врёт: кнопка ещё едет на своё место, и
    координаты из него уже неверны к моменту щелчка.
    """
    deadline = time.monotonic() + max(0.5, timeout_s)
    previous = fingerprint()
    calm_since = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.12)
        current = fingerprint()
        if difference(previous, current) > 0.01:
            previous, calm_since = current, time.monotonic()
            continue
        if time.monotonic() - calm_since >= quiet_s:
            return True
    return False


def fingerprint(shot: Shot | None = None, side: int = 32) -> bytes:
    """Грубый отпечаток картинки: по нему видно, изменился ли экран.

    Считается по уменьшенной до тридцати двух точек копии — это доли миллисекунды
    и никакой видеокарты. Нужен, чтобы не гонять модель зрения на неизменившийся
    кадр: разбор стоит секунды и вытесняет из памяти языковую модель.
    """
    from PIL import Image

    picture = (shot or capture()).image
    small = picture.convert("L").resize((side, side), Image.BILINEAR)
    return small.tobytes()


def difference(first: bytes, second: bytes) -> float:
    """Доля изменившихся точек между двумя отпечатками, 0..1."""
    if not first or not second or len(first) != len(second):
        return 1.0
    changed = sum(1 for a, b in zip(first, second) if abs(a - b) > 12)
    return changed / len(first)
