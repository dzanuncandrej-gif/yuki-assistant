"""Реестр команд. Двуязычный: одинаково понимает русские и английские формулировки.

Новая команда добавляется одним декоратором:

    @register(r"^перезапусти (?P<name>.+)$", name="restart", example="перезапусти проводник")
    def _restart(match): ...

Ранг (`priority`) важнее порядка в файле: узкие системные шаблоны проверяются раньше
широких, иначе «включи звук» уходит в запуск приложения с именем «звук».
"""

from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from re import Pattern
from typing import Any

from . import apps, automation, files, language, media, messengers, outbox, phrases, vision, voices, web
from . import text as text_utils
from . import windows as win
from .apps import AppError
from .automation import ActionError
from .files import FileError
from .messengers import MessengerError
from .outbox import OutboxError
from .vision import VisionError
from .voices import VoiceError
from .web import WebError
from .windows import WindowError

Handler = Callable[[re.Match[str]], str]

FAILURES = (
    ActionError, AppError, FileError, MessengerError, OutboxError, VisionError, VoiceError,
    WebError, WindowError,
)


class Skip(Exception):
    """Шаблон совпал по форме, но фраза не его: пусть разбирают следующие."""

# ранги разбора: чем выше, тем раньше проверяется шаблон
VOICE_INFO = 40  # разговор о голосах: список и проба
VOICE_SET = 30   # переключение голоса — раньше окон, иначе «переключись на атлас» уйдёт в окна
SPECIFIC = 20   # системные действия: питание, звук, окна, файлы, сеть
DEFAULT = 10    # запуск и закрытие приложений
BROAD = 0       # широкие шаблоны вроде поиска в интернете


@dataclass(frozen=True)
class Intent:
    name: str
    pattern: Pattern[str]
    handler: Handler
    example: str
    priority: int = DEFAULT


_REGISTRY: list[Intent] = []
_last_hits: tuple[files.Hit, ...] = ()
_settings: dict[str, Any] = {"ollama_url": "http://127.0.0.1:11434", "search_scope": "home"}

_KEY_NAMES = {
    "энтер": "enter", "ввод": "enter", "эскейп": "esc", "escape": "esc",
    "таб": "tab", "пробел": "space", "контрол": "ctrl", "контрл": "ctrl",
    "шифт": "shift", "альт": "alt", "винда": "win", "виндовс": "win",
    "делит": "delete", "удалить": "delete", "бэкспейс": "backspace",
    "стрелка вверх": "up", "стрелка вниз": "down",
    "стрелка влево": "left", "стрелка вправо": "right",
}

_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def configure(settings: Mapping[str, Any] | None) -> None:
    if settings:
        _settings.update(settings)


def register(
    pattern: str, *, name: str, example: str, priority: int = SPECIFIC
) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        _REGISTRY.append(Intent(name, re.compile(pattern, re.I), handler, example, priority))
        return handler

    return decorator


def _ordered() -> tuple[Intent, ...]:
    return tuple(sorted(_REGISTRY, key=lambda intent: -intent.priority))


def _path(name: str) -> Path:
    return files.locate(name, scope=str(_settings.get("search_scope", "home")))


# «создай на рабочем столе папку тест» — место может стоять где угодно во фразе
_LOCATIONS: tuple[tuple[Pattern[str], str], ...] = (
    (re.compile(r"\s*(?:на|в)\s+(?:рабочем столе|рабочий стол|десктопе|desktop)\s*", re.I), "Desktop"),
    (re.compile(r"\s*(?:в|во)\s+(?:документах|документы|documents)\s*", re.I), "Documents"),
    (re.compile(r"\s*(?:в|во)\s+(?:загрузках|загрузки|downloads)\s*", re.I), "Downloads"),
    (re.compile(r"\s*(?:в|во)\s+(?:картинках|изображениях|pictures)\s*", re.I), "Pictures"),
    (re.compile(r"\s*(?:в|во)\s+(?:музыке|music)\s*", re.I), "Music"),
    (re.compile(r"\s*(?:в|во)\s+(?:видео|videos)\s*", re.I), "Videos"),
)


_base_hint: Path = Path.home() / "Desktop"


def _split_location(text: str) -> tuple[str, Path]:
    """Вырезает указание места и возвращает очищенный текст плюс базовую папку."""
    base = Path.home() / "Desktop"
    cleaned = text
    for pattern, folder in _LOCATIONS:
        if pattern.search(cleaned):
            base = Path.home() / folder
            cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(), base


def _target_path(raw: str, base: Path) -> Path:
    candidate = Path(raw.strip().strip('"'))
    return candidate if candidate.is_absolute() else base / candidate


# ---------------------------------------------------------------- голоса
#
# Имена голосов перечислены прямо в шаблоне: иначе «переключись на браузер» тоже
# считалось бы сменой голоса, а это команда переключения окон.

_VOICE_NAMES = r"(?P<name>юки\w*|jarvis|атлас\w*|atlas|аур\w+|aura)"


@register(
    r"(как\w*\s+(?:есть\s+|доступны\s+)?голос\w*|список голосов|какие голоса|"
    r"каким голосом|какой у тебя голос|list voices|what voices)",
    name="voice_list",
    example="какие есть голоса",
    priority=VOICE_INFO,
)
def _voice_list(_: re.Match[str]) -> str:
    active = voices.active()
    return f"Сейчас {active.title}. Доступны: {voices.summary()}."


@register(
    rf"(?:как звучит|послушать|послушаем|проба голоса|покажи голос|попробуй голос|test voice)\s+"
    rf"(?:голос\s+)?{_VOICE_NAMES}",
    name="voice_test",
    example="как звучит атлас",
    priority=VOICE_INFO,
)
def _voice_test(match: re.Match[str]) -> str:
    profile = voices.resolve(match.group("name"))
    voices.preview(profile)
    return f"Это голос {profile.title}."


@register(
    rf"(?:переключись|переключи|смени|поменяй|включи|поставь|используй|говори|switch to|use)\s+"
    rf"(?:(?:на|как|в|голос|голосом|голоса|voice|to)\s+){{0,3}}{_VOICE_NAMES}",
    name="voice_set",
    example="переключись на атлас",
    priority=VOICE_SET,
)
def _voice_set(match: re.Match[str]) -> str:
    profile = voices.apply(voices.resolve(match.group("name")))
    return f"Голос {profile.title}. {profile.character.capitalize()}."


@register(
    rf"^голос\s+{_VOICE_NAMES}$",
    name="voice_set_short",
    example="голос аура",
    priority=VOICE_SET,
)
def _voice_set_short(match: re.Match[str]) -> str:
    return _voice_set(match)


# ---------------------------------------------------------------- язык
#
# Переключает распознавание речи, ответы модели и голос синтеза все вместе.
# Готовые фразы команд (это «Открыла.», «Готово.» и подобные) языку не подчиняются —
# их перевод отдельная задача, сюда не входит.

_LANGUAGE_WORD = r"(?P<lang>по[\s-]?английски|английск\w*|english|по[\s-]?русски|русск\w*|russian)"


@register(
    rf"^(?:переключись\s+на|переключи\s+на|говори|switch\s+to|speak(?:\s+in)?)\s+{_LANGUAGE_WORD}"
    rf"(?:\s+язык\w*|\s+language)?$",
    name="language_set",
    example="говори по-английски",
    priority=VOICE_SET,
)
def _language_set(match: re.Match[str]) -> str:
    word = match.group("lang").lower()
    code = "en" if ("англ" in word or "english" in word) else "ru"
    language.set_active(code)
    return "Okay, English now." if code == "en" else "Хорошо, снова по-русски."


# ---------------------------------------------------------------- выполнение и ввод


@register(
    r"^(?:выполни|исполни|run|execute)\s+(?:команду|command)\s+(?P<cmd>.+)$",
    name="run",
    example="выполни команду ipconfig",
)
def _run(match: re.Match[str]) -> str:
    return automation.run_command(match.group("cmd"))


# «Напиши Владимиру привет» здесь больше не ловится: раньше такая фраза печаталась
# в активное окно (а «напиши сообщение …» ещё и жала Enter), и сообщение уходило
# туда, где случайно стоял курсор. Просьбы кому-то написать разбирает
# phrases.parse_send, а печать в окно — только явными словами «напечатай», «введи».
@register(
    r"^(?:напечатай|набери\s+текст|введи|type|(?:напиши|write)\s+(?:текст|слово|фразу|text))\s+"
    r"(?:текст\s+|имя\s+|слово\s+|text\s+)?(?P<text>.+)$",
    name="type",
    example="напечатай привет",
)
def _type(match: re.Match[str]) -> str:
    automation.type_text(match.group("text"))
    return "Напечатала."


@register(r"^(?:нажми|press)\s+(?P<keys>.+)$", name="hotkey", example="нажми контрол плюс с")
def _hotkey(match: re.Match[str]) -> str:
    raw = match.group("keys").lower().replace(" плюс ", "+").replace(" plus ", "+").replace(" и ", "+")
    keys = [_KEY_NAMES.get(chunk.strip(), chunk.strip()) for chunk in re.split(r"[+,]", raw)]
    if not keys:
        raise ActionError("не понял, какие клавиши нажать")
    automation.press_hotkey(keys)
    return f"Нажала {'+'.join(keys)}."


# ---------------------------------------------------------------- зрение и экран


@register(
    r"(посмотри на экран|что ты видишь|опиши экран|look at (?:the )?screen|what do you see|describe (?:the )?screen)",
    name="vision_screen",
    example="посмотри на экран",
)
def _vision_screen(_: re.Match[str]) -> str:
    return vision.look_at_screen(str(_settings["ollama_url"]))


@register(
    r"^(?:посмотри|опиши|look at|describe)\s+(?:фото|картинку|изображение|photo|image|picture)\s+(?P<name>.+)$",
    name="vision_file",
    example="посмотри фото отпуск",
)
def _vision_file(match: re.Match[str]) -> str:
    return vision.look_at_file(_path(match.group("name")), str(_settings["ollama_url"]))


@register(
    r"(что (?:сейчас )?на экране|что открыто|what(?:'s| is)? on (?:the )?screen|what.s open)",
    name="screen_context",
    example="что на экране",
)
def _screen(_: re.Match[str]) -> str:
    return win.screen_context()


@register(
    r"(какие\s+(?:окна|программы|приложения)\s+(?:открыты|запущены)|что\s+запущено|"
    r"(?:list|show)\s+(?:open\s+)?(?:windows|apps|programs))",
    name="running",
    example="какие программы запущены",
)
def _running(_: re.Match[str]) -> str:
    items = apps.running()
    return "Открыты: " + ", ".join(items) if items else "Открытых окон нет."


# ---------------------------------------------------------------- живые запросы в сеть


@register(
    r"(?:какая\s+)?(?:погод[аеу]|weather)(?:\s+(?:на\s+)?(?:сегодня|сейчас|завтра|today|now))?"
    r"(?:\s+(?:в|во|in)\s+(?P<city>[^,.?]+))?",
    name="weather",
    example="какая погода на сегодня",
)
def _weather(match: re.Match[str]) -> str:
    return web.weather(match.group("city"))


_MUSIC_WORDS = r"(?:музык\w*|музон\w*|песн\w*|песенк\w*|трек\w*|плейлист\w*|music|song|songs)"
_VIDEO_WORDS = (
    r"(?:видео|видос\w*|ролик\w*|клип\w*|фильм\w*|мультик\w*|мультфильм\w*|сериал\w*|"
    r"трейлер\w*|обзор\w*|video|videos)"
)
_PLAY = r"(?:включи|включить|включай|поставь|запусти|вруби|врубай|сыграй|проиграй|play|put\s+on)"
_OTHER = r"(?:другую|другой|другое|следующую|следующий|следующее|новую|новый|иную|another)"
_YOUTUBE = r"(?:ютуб\w*|youtube)"
# слова-заглушки перед «музыку»: «какую-нибудь», «мне», «любую»
_FILLER_MOD = re.compile(r"\b(?:мне|какую[\s-]*(?:нибудь|то)|любую|что[\s-]*нибудь|немного|пожалуйста)\b",
                         re.IGNORECASE)

# После «включи» или «поставь» бывает и не музыка: таймер, свет, режим. Такие
# просьбы в музыку не превращаем — их разберёт агент.
_NOT_MEDIA = re.compile(
    r"^(?:таймер|будильник|напоминани|звук|свет|вай|wi|интернет|блютуз|bluetooth|компьютер|пк|"
    r"камер|микрофон|режим|голос|субтитр|громкост|яркост|на\s+паузу|паузу|ночн|тёмн|темн|светл|"
    r"авиа|обновлени|запись|трансляц|экран|уведомлен|автозапуск|впн|vpn|прокси|задач|"
    r"напомин|сигнал|оценк|лайк|пароль|ударени)",
    re.IGNORECASE,
)


@register(
    rf"^(?:{_PLAY}|переключи|смени|давай)\s+(?:на\s+)?{_OTHER}(?:\s+(?:{_MUSIC_WORDS}|{_VIDEO_WORDS}))?$"
    rf"|^(?:переключи|смени|пропусти)\s+(?:эту\s+|этот\s+)?(?:{_MUSIC_WORDS}|{_VIDEO_WORDS})$"
    rf"|^{_PLAY}\s+что[\s-]*(?:нибудь|то)\s+другое$"
    rf"|^(?:следующ\w+|дальше|next|skip)(?:\s+(?:{_MUSIC_WORDS}|{_VIDEO_WORDS}))?$",
    name="media_next",
    example="включи другую песню",
)
def _media_next(_: re.Match[str]) -> str:
    """«Другую песню» — это следующий трек, а не поиск песни «другая»."""
    media.next_track()
    return "Переключила."


@register(
    rf"^(?P<verb>{_PLAY}|покажи|найди|поищи|открой)\s+(?:мне\s+)?(?:(?:на|в)\s+{_YOUTUBE}\s+)?"
    rf"(?P<kind>{_VIDEO_WORDS})(?:\s+(?P<query>.+))?$",
    name="video",
    example="включи видео про котиков",
)
def _video(match: re.Match[str]) -> str:
    """Видео ищется и включается на YouTube.

    Раньше «включи видео про котиков» пыталось запустить приложение с именем
    «видео про котиков», а «покажи видео» искало файлы на диске.
    """
    kind = match.group("kind").lower()
    query = re.sub(r"^(?:про|о|об|на\s+тему)\s+", "", (match.group("query") or "").strip(), flags=re.I)
    if not kind.startswith(("видео", "видос", "ролик", "video")):
        query = f"{kind} {query}".strip()  # «фильм Интерстеллар», «клип Believer»
    if not query:
        automation.open_url("https://www.youtube.com")
        return "Открыла YouTube. Что включить?"
    if match.group("verb").lower() in ("найди", "поищи"):
        return f"Открыла на YouTube: {media.search_youtube(query)}."
    return f"Включаю {media.play_video(query)}."


@register(
    rf"^(?P<verb>{_PLAY}|покажи|найди|поищи|открой)\s+(?:мне\s+)?(?:на|в)\s+{_YOUTUBE}\s+(?P<query>.+)$"
    rf"|^(?P<verb2>{_PLAY}|покажи|найди|поищи)\s+(?:мне\s+)?(?P<query2>.+?)\s+(?:на|в|с)\s+{_YOUTUBE}$",
    name="youtube",
    example="найди на ютубе обзор айфона",
)
def _youtube(match: re.Match[str]) -> str:
    verb = (match.group("verb") or match.group("verb2") or "").lower()
    query = (match.group("query") or match.group("query2") or "").strip()
    if verb in ("найди", "поищи"):
        return f"Открыла на YouTube: {media.search_youtube(query)}."
    return f"Включаю {media.play_video(query)}."


@register(
    rf"^{_PLAY}\s+(?P<mod>(?:[\w-]+\s+){{0,3}}?){_MUSIC_WORDS}(?:\s+(?P<query>.+))?$",
    name="music",
    example="включи музыку / включи песню Believer",
)
def _music(match: re.Match[str]) -> str:
    mod = _FILLER_MOD.sub(" ", match.group("mod") or "").strip()
    query = re.sub(r"^(?:про|by)\s+", "", (match.group("query") or "").strip(), flags=re.I)
    if re.match(r"^(?:из|с|со|для|from)\s", query, re.I):
        query = f"музыка {query}"  # «музыку из Интерстеллара»
    if mod and not query:
        request = f"{mod} музыка"  # «спокойную музыку»
    else:
        request = " ".join(part for part in (mod, query) if part)
    if not request:
        media.play_music(None)
        return "Включаю музыку."
    return f"Включаю {media.play_music(request)}."


@register(
    r"^(?:поставь|вруби|врубай|сыграй|проиграй)\s+(?:мне\s+)?(?P<query>.+)$",
    name="play_named",
    example="поставь Кино Группа крови",
    priority=BROAD,
)
def _play_named(match: re.Match[str]) -> str:
    """«Поставь Моргенштерна» — это трек, если только речь не о таймере или режиме."""
    query = match.group("query").strip()
    if _NOT_MEDIA.match(query):
        raise Skip()
    return f"Включаю {media.play_music(query)}."


# Поиск и справки («найди в интернете…», «что такое…») намеренно уходят агенту:
# он читает выдачу инструментом web_search и отвечает связной фразой, а не куском страницы.


@register(
    r"^(?:какие|что\s+по)?\s*(?:у\s+нас\s+)?(?:(?:на\s+)?сегодня\s+)?новости"
    r"(?:\s+(?:на\s+)?сегодня)?[\s?]*$"
    r"|^(?:что|чего)\s+(?:нового|новенького)[\s?]*$"
    r"|^(?:покажи|открой|включи|прочитай|расскажи|show|open)\s+(?:мне\s+)?новости"
    r"(?:\s+на\s+сегодня)?[\s?]*$|^news$",
    name="news", example="какие новости",
)
def _news(_: re.Match[str]) -> str:
    """Открывает ленту и сразу зачитывает заголовки.

    Раньше страница просто открывалась молча, и человеку приходилось читать
    самому. Голосовому помощнику полагается прочесть вслух то, что он открыл.
    """
    web.open_url("https://news.google.com/topstories?hl=ru")
    try:
        stories = web.news("главное", count=4)
        digest = web.summarize_results(stories, limit=4)
    except Exception:
        digest = ""
    return f"Открыла новости. {digest}".strip() if digest else "Открыла новости."


@register(
    r"^(?:давай\s+)?(?:по)?игра(?:ем|ть|й)\b.*$|^(?:хочу|хочется)\s+(?:по)?играть\b.*$"
    r"|^(?:запусти|открой|включи)\s+(?:игру|игры|games?)\b.*$|^let'?s\s+play\b.*$",
    name="play_games", example="давай поиграем",
)
def _play(_: re.Match[str]) -> str:
    """«Давай поиграем» — это Steam, а не поиск бесплатных игр в браузере.

    Без этого правила фраза уходила агенту, тот не видел в ней приложения и
    честно шёл искать игры в интернете. Библиотека игр у человека уже есть.
    """
    launched = apps.launch("steam")
    return f"Запускаю {launched}. Выбирай, во что играем."


# ---------------------------------------------------------------- окна


@register(
    r"^(?:сверни|скрой|minimize)\s+(?:всё|все окна|все|all|everything)$|^покажи рабочий стол$|^show desktop$",
    name="minimize_all",
    example="сверни всё",
)
def _minimize_all(_: re.Match[str]) -> str:
    automation.minimize_all()
    return "Свернула всё."


@register(
    r"^(?:сверни|скрой|minimize)(?:\s+(?:окно|window))?(?:\s+(?P<name>.+))?$",
    name="minimize_window",
    example="сверни окно / сверни хром",
)
def _minimize(match: re.Match[str]) -> str:
    name = match.group("name")
    if name:
        return f"Свернула {win.minimize(win.find(name))}."
    return f"Свернула {win.minimize_active()}."


@register(
    r"^(?:разверни|раскрой|maximize)(?:\s+(?:окно|window))?(?:\s+(?P<name>.+))?$",
    name="maximize_window",
    example="разверни окно",
)
def _maximize(match: re.Match[str]) -> str:
    name = match.group("name")
    if name:
        return f"Развернула {win.maximize(win.find(name))}."
    return f"Развернула {win.maximize_active()}."


@register(
    r"^(?:закрой|close)\s+(?:это\s+|this\s+)?(?:окно|window)$",
    name="close_window",
    example="закрой окно",
)
def _close_window(_: re.Match[str]) -> str:
    return f"Закрыла {win.close_active()}."


@register(
    r"^(?:переключись на|покажи окно|активируй|switch to|focus)\s+(?P<name>.+)$",
    name="focus_window",
    example="переключись на браузер",
)
def _focus(match: re.Match[str]) -> str:
    return f"Переключилась на {win.focus(win.find(match.group('name')))}."


# ---------------------------------------------------------------- файлы: обзор и чтение


@register(
    r"^(?:что в|покажи содержимое|открой список|browse|list|show contents of)\s+"
    r"(?:папке|папки|папку|folder|directory)?\s*(?P<name>.+)$",
    name="browse",
    example="что в папке загрузки",
)
def _browse(match: re.Match[str]) -> str:
    return files.browse(_path(match.group("name")))


@register(
    r"^(?:прочитай|прочти|read)\s+(?:файл|file)?\s*(?P<name>.+)$",
    name="read_file",
    example="прочитай файл заметки",
)
def _read(match: re.Match[str]) -> str:
    target = _path(match.group("name"))
    return f"{target.name}: {files.read_text(target)}"


@register(
    r"(сколько места|сколько свободно|состояние дисков|disk space|free space|drives)",
    name="disks",
    example="сколько места на дисках",
)
def _disks(_: re.Match[str]) -> str:
    return files.disks()


# ---------------------------------------------------------------- файлы: изменение


@register(
    r"^(?:создай|сделай|create|make)\s+(?:новую\s+|new\s+)?(?:папку|директорию|folder|directory)\s+(?P<name>.+)$",
    name="mkdir",
    example="создай на рабочем столе папку отчёты",
)
def _mkdir(match: re.Match[str]) -> str:
    name, base = _split_location(match.group("name"))
    target = files.make_folder(_target_path(name, base if base != Path.home() / "Desktop" else _base_hint))
    return f"Создала папку {target.name} в {target.parent.name}."


@register(
    r"^(?:создай|сделай|create|make)\s+(?:новый\s+|new\s+)?(?:файл|file)\s+(?P<name>[^\s]+)"
    r"(?:\s+(?:с текстом|с содержимым|with text|containing)\s+(?P<content>.+))?$",
    name="create_file",
    example="создай на рабочем столе файл список с текстом молоко",
)
def _create_file(match: re.Match[str]) -> str:
    name, base = _split_location(match.group("name"))
    content, _ = _split_location(match.group("content") or "")
    target = _target_path(name, base if base != Path.home() / "Desktop" else _base_hint)
    files.write_text(target, content)
    return f"Создала {target.name} в {target.parent.name}."


@register(
    r"^(?:допиши|добавь в файл|append to)\s+(?P<name>\S+)\s+(?P<content>.+)$",
    name="append_file",
    example="допиши заметки купить кофе",
)
def _append_file(match: re.Match[str]) -> str:
    target = _path(match.group("name"))
    files.write_text(target, match.group("content"), append=True)
    return f"Дописала в {target.name}."


@register(
    # слово «файл» или «папку» обязательно: «удали сообщение» не должно искать
    # на диске файл с именем «сообщение» и отправлять его в корзину
    r"^(?:удали|delete|remove)\s+(?P<forever>навсегда\s+|permanently\s+)?"
    r"(?:файл|папку|file|folder)\s+(?P<name>.+)$",
    name="delete",
    example="удали файл старый отчёт",
)
def _delete(match: re.Match[str]) -> str:
    target = _path(match.group("name"))
    permanent = bool(match.group("forever"))
    name = files.delete(target, permanent=permanent)
    return f"Удалила {name} {'безвозвратно' if permanent else 'в корзину'}."


@register(
    r"^(?:скопируй|copy)\s+(?P<src>.+?)\s+(?:в|to)\s+(?P<dst>.+)$",
    name="copy",
    example="скопируй отчёт в документы",
)
def _copy(match: re.Match[str]) -> str:
    result = files.copy(_path(match.group("src")), _path(match.group("dst")))
    return f"Скопировала в {result}."


@register(
    r"^(?:перемести|move)\s+(?P<src>.+?)\s+(?:в|to)\s+(?P<dst>.+)$",
    name="move",
    example="перемести отчёт в документы",
)
def _move(match: re.Match[str]) -> str:
    result = files.move(_path(match.group("src")), _path(match.group("dst")))
    return f"Переместила в {result}."


@register(
    r"^(?:переименуй|rename)\s+(?P<src>.+?)\s+(?:в|to)\s+(?P<name>.+)$",
    name="rename",
    example="переименуй отчёт в итог",
)
def _rename(match: re.Match[str]) -> str:
    result = files.rename(_path(match.group("src")), match.group("name").strip())
    return f"Теперь это {result.name}."


# ---------------------------------------------------------------- файлы: поиск


@register(
    r"^(?:найди|покажи|открой|find|show)\s+(?P<category>фото|документы|photos?|documents)"
    r"(?:\s+(?:про|с|по|about|with)?\s*(?P<query>.+))?$",
    name="find_media",
    example="найди видео отпуск",
)
def _find_media(match: re.Match[str]) -> str:
    global _last_hits
    category = {"музыку": "музыка"}.get(match.group("category").lower(), match.group("category").lower())
    _last_hits = files.search(match.group("query") or "", category=category)
    if not _last_hits:
        return f"Не нашла {category}."
    names = [hit.path.name for hit in _last_hits[:3]]
    return f"Нашла: {', '.join(names)}. Скажи «открой первый»."


@register(
    r"^(?:найди|поищи|find)\s+(?:файл|файлы|папку|file|files|folder)\s+(?P<query>.+)$",
    name="find_files",
    example="найди файл отчёт",
)
def _find_files(match: re.Match[str]) -> str:
    global _last_hits
    _last_hits = files.search(match.group("query"), scope=str(_settings.get("search_scope", "home")))
    if not _last_hits:
        return "Ничего не нашла."
    names = [hit.path.name for hit in _last_hits[:3]]
    tail = f" и ещё {len(_last_hits) - 3}" if len(_last_hits) > 3 else ""
    return f"Нашла: {', '.join(names)}{tail}. Скажи «открой первый», чтобы открыть."


@register(
    r"^(?:открой|open)\s+(?:первый|первое|найденное|first|it)$",
    name="open_hit",
    example="открой первый",
)
def _open_hit(_: re.Match[str]) -> str:
    if not _last_hits:
        raise FileError("сначала нужно что-нибудь найти")
    return f"Открываю {files.open_path(_last_hits[0].path)}."


@register(
    r"^(?:открой|open)\s+(?:папку|folder)\s+(?P<name>.+)$",
    name="open_folder",
    example="открой папку загрузки",
)
def _open_folder(match: re.Match[str]) -> str:
    return f"Открываю {files.open_folder(match.group('name'))}."


# ---------------------------------------------------------------- звук, медиа, экран


@register(
    r"(?:громкость|volume)\s+(?:на\s+|to\s+)?(?P<value>\d{1,3})",
    name="volume_set",
    example="громкость 30",
)
def _volume_set(match: re.Match[str]) -> str:
    return f"Громкость {automation.volume_set(int(match.group('value')))} процентов."


@register(
    r"(громче|прибавь звук|сделай звук громче|volume up|louder|turn up (?:the )?(?:volume|sound)|"
    r"make (?:the )?(?:sound|volume) louder)",
    name="volume_up",
    example="громче",
)
def _volume_up(_: re.Match[str]) -> str:
    value = automation.volume_step(10)
    return f"Громкость {value} процентов." if value >= 0 else "Громче."


@register(
    r"(тише|убавь звук|сделай звук тише|volume down|quieter|turn down (?:the )?(?:volume|sound)|"
    r"make (?:the )?(?:sound|volume) (?:quieter|lower))",
    name="volume_down",
    example="тише",
)
def _volume_down(_: re.Match[str]) -> str:
    value = automation.volume_step(-10)
    return f"Громкость {value} процентов." if value >= 0 else "Тише."


@register(
    r"(какая\s+(?:\w+\s+)?громкость|уровень\s+громкости|what.s the volume|current volume)",
    name="volume_get",
    example="какая громкость",
)
def _volume_get(_: re.Match[str]) -> str:
    return f"Громкость {automation.volume_get()} процентов."


@register(
    r"(выключи звук|включи звук|без звука|mute|unmute|silence)",
    name="mute",
    example="выключи звук",
)
def _mute(_: re.Match[str]) -> str:
    return f"Звук {automation.mute_toggle()}."


@register(
    r"^(?:выключи|выруби|останови|стоп|заглуши|прекрати|хватит|turn off|stop)\s*"
    r"(?:воспроизведение\s*)?(?:музык\w*|песн\w*|трек\w*|музон|плеер|аудио|видео|ролик|music|song)\b"
    r"|^(?:музык\w*|песн\w*)\s+(?:выключи|стоп|хватит)\b",
    name="media_stop",
    example="выключи музыку",
    priority=SPECIFIC,
)
def _stop_music(_: re.Match[str]) -> str:
    """Останавливает воспроизведение.

    Отдельно от паузы: «выключи музыку» человек говорит постоянно, а шаблона на
    это не было вовсе. Фраза уходила в модель, та видела инструмент play_music —
    и вместо остановки включала музыку заново.
    """
    automation.media("play_pause")
    return "Выключила."


# Только целая фраза. Раньше шаблон искал «play» где угодно, и «открой
# playstation» или «display» ставили музыку на паузу.
@register(
    r"^(?:пауза|на\s+паузу|поставь\s+на\s+паузу|сними\s+с\s+паузы|продолжи\s+(?:воспроизведение|"
    r"музыку|видео|песню)|play|pause|resume)$",
    name="media_play",
    example="пауза",
)
def _play(_: re.Match[str]) -> str:
    automation.media("play_pause")
    return "Готово."


@register(
    r"^(?:предыдущ\w+\s+(?:трек|песн\w+|видео)|верни\s+(?:прошлую|предыдущую)\s+песню|"
    r"previous track|previous song)$",
    name="media_prev",
    example="предыдущий трек",
)
def _prev(_: re.Match[str]) -> str:
    automation.media("prev")
    return "Предыдущий."


@register(
    r"(?:яркость|brightness)\s+(?:на\s+|to\s+)?(?P<value>\d{1,3})",
    name="brightness_set",
    example="яркость 60",
)
def _brightness_set(match: re.Match[str]) -> str:
    return f"Яркость {automation.brightness_set(int(match.group('value')))} процентов."


@register(
    r"(какая\s+(?:\w+\s+)?яркость|уровень\s+яркости|what.s the brightness)",
    name="brightness_get",
    example="какая яркость",
)
def _brightness_get(_: re.Match[str]) -> str:
    return f"Яркость {automation.brightness_get()} процентов."


@register(
    r"(скриншот|снимок экрана|screenshot|screen shot|capture (?:the )?screen)",
    name="screenshot",
    example="сделай скриншот",
)
def _screenshot(_: re.Match[str]) -> str:
    return f"Снимок сохранён: {automation.screenshot().name}"


# ---------------------------------------------------------------- сессия и питание


@register(
    r"^(?:отмени|отмена|cancel|stop)(?:\s*(?:выключени[ея]|перезагрузк[уи]|таймер|shutdown|restart))?$",
    name="power_cancel",
    example="отмена выключения",
)
def _power_cancel(_: re.Match[str]) -> str:
    automation.power_cancel()
    return "Отменила."


@register(
    r"(выключи компьютер|выключи пк|заверши работу|shut ?down|turn off (?:the )?(?:pc|computer))",
    name="power_off",
    example="выключи компьютер",
)
def _power_off(_: re.Match[str]) -> str:
    delay = automation.power("shutdown")
    return f"Выключаю компьютер через {delay} секунд. Скажи «отмена», если передумал."


@register(
    r"(перезагрузи компьютер|перезагрузи пк|перезагрузка|reboot|restart (?:the )?(?:pc|computer))",
    name="power_restart",
    example="перезагрузи компьютер",
)
def _power_restart(_: re.Match[str]) -> str:
    delay = automation.power("restart")
    return f"Перезагружаю через {delay} секунд. Скажи «отмена», если передумал."


@register(r"(выйди из системы|смени пользователя|log ?off|sign out)", name="logoff", example="выйди из системы")
def _logoff(_: re.Match[str]) -> str:
    automation.power("logoff")
    return "Завершаю сеанс."


@register(r"(гибернация|в гибернацию|hibernate)", name="hibernate", example="гибернация")
def _hibernate(_: re.Match[str]) -> str:
    automation.power("hibernate")
    return "Ухожу в гибернацию."


@register(
    r"(заблокируй (?:компьютер|экран)|lock (?:pc|screen|the computer))",
    name="lock",
    example="заблокируй компьютер",
)
def _lock(_: re.Match[str]) -> str:
    automation.lock_workstation()
    return "Блокирую."


@register(r"(спящий режим|усыпи компьютер|уйди в сон|sleep mode|go to sleep)", name="sleep", example="спящий режим")
def _sleep(_: re.Match[str]) -> str:
    automation.sleep_pc()
    return "Ухожу в сон."


@register(r"(очисти корзину|опустоши корзину|empty (?:the )?(?:recycle bin|trash))", name="recycle", example="очисти корзину")
def _recycle(_: re.Match[str]) -> str:
    automation.empty_recycle_bin()
    return "Корзина очищена."


@register(
    r"^(?:сними задачу|убей процесс|принудительно закрой|kill|force close)\s+(?P<name>.+)$",
    name="kill",
    example="убей процесс chrome",
)
def _kill(match: re.Match[str]) -> str:
    return f"Завершила {automation.kill_process(match.group('name'))}."


@register(r"(выключи (?:вайфай|wi-?fi|интернет)|turn off wi-?fi)", name="wifi_off", example="выключи вайфай")
def _wifi_off(_: re.Match[str]) -> str:
    return f"Отключила {automation.network_adapter(False)}."


@register(r"(включи (?:вайфай|wi-?fi|интернет)|turn on wi-?fi)", name="wifi_on", example="включи вайфай")
def _wifi_on(_: re.Match[str]) -> str:
    return f"Включила {automation.network_adapter(True)}."


@register(r"(что в буфере|прочитай буфер|буфер обмена|clipboard)", name="clipboard", example="что в буфере")
def _clipboard(_: re.Match[str]) -> str:
    content = automation.get_clipboard()
    return f"В буфере: {content[:300]}" if content else "Буфер обмена пуст."


@register(
    r"(загрузка системы|загрузка процессора|состояние системы|сколько памяти|заряд батареи|"
    r"system status|cpu usage|battery)",
    name="stats",
    example="состояние системы",
)
def _stats(_: re.Match[str]) -> str:
    return automation.system_stats()


@register(
    r"(котор\w*\s+(?:сейчас\s+)?час|сколько\s+(?:сейчас\s+)?времени|what\s+time|what.s the time|time now)",
    name="time",
    example="который час",
)
def _time(_: re.Match[str]) -> str:
    return "Сейчас " + dt.datetime.now().strftime("%H:%M")


@register(
    r"(как\w*\s+(?:сегодня\s+)?(?:число|дата)|какое сегодня|what.s the date|what date|today.s date)",
    name="date",
    example="какое сегодня число",
)
def _date(_: re.Match[str]) -> str:
    now = dt.datetime.now()
    return f"Сегодня {now.day} {_MONTHS[now.month - 1]} {now.year} года"


@register(
    r"^(?:отмени|верни|откати)\s*(?:последнее|последний|назад|это|обратно)?$|^undo$",
    name="undo",
    example="отмени последнее",
)
def _undo(_: re.Match[str]) -> str:
    from . import journal

    return journal.undo_last().capitalize()


@register(
    r"(что ты (?:делал|сделал)|последние действия|журнал действий|что было сделано)",
    name="journal",
    example="что ты сделал",
)
def _journal(_: re.Match[str]) -> str:
    from . import journal

    return journal.summary()


@register(
    r"(что ты умеешь|список команд|твои возможности|help|what can you do)",
    name="help",
    example="что ты умеешь",
)
def _help(_: re.Match[str]) -> str:
    return (
        "Управляю компьютером: открываю и закрываю программы и игры, командую окнами, "
        "ищу и правлю файлы, печатаю текст, жму клавиши и кликаю мышью. "
        "Ищу в интернете, читаю новости и погоду, включаю музыку, пишу в мессенджеры, "
        "делаю скриншоты и рассказываю, что вижу на экране."
    )


# ---------------------------------------------------------------- приложения (широкие шаблоны)


@register(
    r"^(?:закрой|заверши|убей|close|quit|exit)\s+(?:приложение\s+|программу\s+|игру\s+|app\s+)?(?P<name>.+)$",
    name="close_app",
    example="закрой блокнот",
    priority=DEFAULT,
)
def _close_app(match: re.Match[str]) -> str:
    return f"Закрыла {apps.close(match.group('name'))}."


@register(
    r"^(?P<verb>открой|открыть|запусти|запустить|включи|включить|open|launch|start|run)\s+"
    r"(?:сайт\s+|приложение\s+|программу\s+|игру\s+|app\s+|the\s+)?(?P<name>.+)$",
    name="open",
    example="открой телеграм / запусти кс2",
    priority=DEFAULT,
)
def _open(match: re.Match[str]) -> str:
    """Сайт, затем приложение. «Включи Моргенштерна» без такого приложения — музыка."""
    verb = match.group("verb").lower()
    name = match.group("name").strip()
    site = automation.open_site(name)
    if site:
        return f"Открываю {site}."
    try:
        # ждём появления окна и выводим его вперёд, чтобы следующая команда печатала туда
        return f"Запускаю {apps.launch_and_focus(name)}."
    except AppError:
        if verb.startswith("включ") and not _NOT_MEDIA.match(name):
            return f"Включаю {media.play_music(name)}."
        raise


@register(
    r"^(?:открой|найди)\s+(?:чат|переписку|диалог)\s+с\s+(?P<contact>.+?)(?:\s+(?:в|во)\s+(?P<app>\S+))?$",
    name="open_chat",
    example="открой чат с Владимиром",
)
def _open_chat(match: re.Match[str]) -> str:
    app = phrases.APPS.get((match.group("app") or "").lower(), "telegram")
    draft = outbox.prepare(app, match.group("contact"))
    if not draft.found:
        raise OutboxError(f"в {draft.service.title} не нашла «{match.group('contact')}»")
    outbox.open_found(draft)
    return f"Открыла чат «{draft.found}»."


# Широкие запросы вроде «найди рецепт борща» намеренно не перехватываются:
# агент решит сам — поискать в сети и ответить голосом или открыть выдачу в браузере.


# ---------------------------------------------------------------- точка входа


def catalog() -> tuple[Intent, ...]:
    return tuple(_REGISTRY)


def capabilities() -> str:
    return "; ".join(sorted({intent.example for intent in _REGISTRY}))


def match_intent(text: str) -> str | None:
    """Имя интента, который сработает на фразе. Нужно для журнала в интерфейсе."""
    normalized = text_utils.normalize(text)
    if parse_message(normalized) is not None:
        return "messenger_send"
    for intent in _ordered():
        if intent.pattern.search(normalized):
            return intent.name
    return None


# «открой телеграм и напиши привет» — делим только там, где дальше идёт глагол команды
_CHAIN = re.compile(
    r"\s*(?:,\s*)?\b(?:и\s+потом|и\s+затем|а\s+потом|а\s+затем|and\s+then|и|потом|затем|then|and)\s+"
    r"(?=(?:открой|запусти|включи|выключи|закрой|сверни|разверни|напиши|напечатай|набери|введи|"
    r"отправь|нажми|найди|создай|удали|скопируй|перемести|переименуй|прочитай|поставь|сделай|"
    r"покажи|переключи|вруби|поищи|"
    r"open|launch|start|run|close|type|write|send|press|find|create|delete|copy|move|rename|read|play|make|take)\b)",
    re.IGNORECASE,
)

# ответ, по которому видно, что быстрый путь не справился и нужен агент
_FAILED = ("Не смог", "Ошибка при выполнении")


def _failed(answer: str | None) -> bool:
    return answer is None or answer.startswith(_FAILED)


def _run_single(phrase: str) -> str | None:
    """Разбор и выполнение одной команды. Возвращает None, если шаблон не совпал."""
    global _base_hint

    request = parse_message(phrase)
    if request is not None:
        return _send_composite(request)

    cleaned, base = _split_location(phrase)
    _base_hint = base
    candidates = (cleaned, phrase) if cleaned != phrase else (phrase,)

    for text in candidates:
        for intent in _ordered():
            match = intent.pattern.search(text)
            if not match:
                continue
            try:
                return intent.handler(match)
            except Skip:
                continue
            except FAILURES as err:
                return f"Не смог: {err}"
            except Exception as err:
                return f"Ошибка при выполнении «{intent.name}»: {err}"
    return None


def _known_contact(name: str) -> bool:
    return messengers.knows(name)


def parse_message(text: str) -> phrases.SendRequest | None:
    """Просьба кому-то написать: мессенджер, адресат и текст — разбирается целиком."""
    return phrases.parse_send(text, known_contact=_known_contact)


# ---------------------------------------------------------------- сообщения с переспросом

_PENDING_TTL_S = 45.0
_pending: dict[str, Any] = {"kind": "", "request": None, "draft": None, "until": 0.0}

_CANCEL = re.compile(r"^(?:отмена|отмени|не\s+надо|не\s+отправляй|нет|стоп|забудь|передумал\w*)\b", re.I)
_YES = re.compile(r"^(?:да|ага|угу|верно|точно|он|она|отправляй|отправь|давай|конечно|именно|yes)\b", re.I)


def _set_pending(kind: str, request: phrases.SendRequest, draft: outbox.Draft | None = None) -> None:
    _pending.update(kind=kind, request=request, draft=draft, until=time.monotonic() + _PENDING_TTL_S)


def _clear_pending() -> None:
    _pending.update(kind="", request=None, draft=None, until=0.0)


def pending_question() -> str:
    """Чего ждёт быстрый путь: «message» — текст, «confirm» — подтверждение адресата."""
    if _pending["kind"] and time.monotonic() > float(_pending["until"]):
        _clear_pending()
    return str(_pending["kind"])


def _resume_pending(text: str) -> str | None:
    """Ответ человека на вопрос «что написать?» или «это он?»."""
    kind = pending_question()
    if not kind:
        return None
    request: phrases.SendRequest = _pending["request"]
    draft: outbox.Draft | None = _pending["draft"]
    _clear_pending()

    if kind == "message":
        if _CANCEL.match(text):
            return "Хорошо, не пишу."
        return _send_composite(replace(request, message=text.strip()))

    if _YES.match(text) and draft is not None:
        draft.confirmed = True
        try:
            outbox.deliver(draft, request.message)
        except FAILURES as err:
            return f"Не смогла отправить: {err}"
        return f"Отправила «{request.message}» — {draft.found}."
    if _CANCEL.match(text):
        outbox.cancel()
        return "Не отправляю."
    outbox.cancel()
    return None  # сказали что-то другое — разбираем как обычную просьбу


def _send_composite(request: phrases.SendRequest) -> str:
    """Отправка с проверкой адресата по дереву интерфейса мессенджера.

    Нет текста — спрашиваем, что написать. Имя совпало неуверенно или нашлось
    несколько похожих — спрашиваем, тот ли человек. Сообщение, ушедшее не тому,
    вернуть нельзя, поэтому здесь лучше переспросить, чем угадать.
    """
    who = request.contact
    if not request.message:
        _set_pending("message", request)
        return f"Что написать {who}?"
    try:
        draft = outbox.prepare(request.app, who)
        if not draft.found:
            others = f" Похожие: {', '.join(draft.candidates[:3])}." if draft.candidates else ""
            return f"Не нашла «{who}» в {draft.service.title}.{others}"
        outbox.open_found(draft)
        if not draft.certain:
            _set_pending("confirm", request, draft)
            return f"Нашла «{draft.found}». Это нужный человек? Скажи «да» — отправлю."
        outbox.deliver(draft, request.message)
    except FAILURES as err:
        return f"Не смогла отправить: {err}"
    except Exception as err:
        return f"Не смогла отправить: {err}"
    return f"Отправила {draft.found}: «{request.message}»."


# ---------------------------------------------------------------- точка входа


@dataclass(frozen=True)
class Outcome:
    """Итог быстрого разбора.

    answer    — что уже сделано (или None, если ничего);
    remainder — часть просьбы, с которой быстрый путь не справился: её доделывает агент;
    failure   — текст неудачи, если она была.
    """

    answer: str | None
    remainder: str = ""
    failure: str | None = None


def handle_plan(text: str) -> Outcome:
    """Выполняет всё, что умеет быстро, и честно отдаёт остаток агенту.

    Раньше цепочка «открой ютуб и включи видео про котиков» докладывала «Открываю
    ютуб. Не смог…» как успех — вторая половина молча пропадала. Теперь цепочка
    останавливается на первой неудаче, а невыполненный хвост уходит агенту.
    """
    normalized = text_utils.normalize(text)
    if not normalized:
        return Outcome(None)

    resumed = _resume_pending(normalized)
    if resumed is not None:
        return Outcome(resumed)

    request = parse_message(normalized)
    if request is not None:
        return Outcome(_send_composite(request))

    parts = [part.strip(" ,.") for part in _CHAIN.split(normalized) if part and part.strip(" ,.")]
    done: list[str] = []
    for index, part in enumerate(parts):
        typed = re.match(r"^(?:напиши|напечатай)\s+(?P<text>.+)$", part, re.I)
        if index > 0 and done and typed and parse_message(part) is None:
            # «открой блокнот и напиши привет»: окно только что открыто — печатаем туда
            try:
                automation.type_text(typed.group("text"))
                done.append("Напечатала.")
                continue
            except FAILURES as err:
                answer: str | None = f"Не смог: {err}"
        else:
            answer = _run_single(part)
        if _failed(answer):
            return Outcome(" ".join(done) or None, " и ".join(parts[index:]), answer)
        done.append(str(answer))
    return Outcome(" ".join(done) or None)


def handle(text: str) -> str | None:
    """Ответ, если фраза целиком выполнена быстрым путём; текст неудачи или None иначе."""
    outcome = handle_plan(text)
    if outcome.remainder:
        return outcome.failure if not outcome.answer else None
    return outcome.answer


_LAUNCH_VERBS = re.compile(
    r"^(?:открой|открыть|запусти|запустить|включи|включить|open|launch|start|run)\s+(?P<name>.+)$",
    re.I,
)


def fallback(text: str) -> str | None:
    """Последняя попытка перед LLM: фраза похожа на запуск, но шаблоны не сработали."""
    normalized = text_utils.normalize(text)
    match = _LAUNCH_VERBS.match(normalized)
    if not match:
        return None
    name = match.group("name").strip()
    try:
        return f"Запускаю {apps.launch_and_focus(name)}."
    except AppError:
        return None


def open_last_path() -> Path | None:
    return _last_hits[0].path if _last_hits else None
