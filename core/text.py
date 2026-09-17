"""Нормализация распознанной речи перед разбором команд.

Whisper отдаёт фразу целиком: «Юки, открой телеграм, пожалуйста.» Без очистки
обращения и вежливых слов шаблоны команд не совпадают, запрос уходит в LLM,
и та рапортует о действии, которого никто не выполнял.
"""

from __future__ import annotations

import re
from typing import Pattern

# имена, на которые ассистент откликается: у каждого голоса своё обращение
WAKE_NAMES: dict[str, tuple[str, ...]] = {
    "jarvis": (
        "юки", "джарвиз", "джарис", "джавис", "джарвес", "джервис", "чарвис",
        "джарвиc", "жарвис", "jarvis", "jervis", "jarvice",
    ),
    "atlas": ("атлас", "атлаз", "отлас", "атлант", "atlas", "atlant"),
    # короткие созвучия вроде «ора» сюда не попадают: шум комнаты будил бы ассистента
    "aura": ("аура", "ауру", "ауро", "aura", "аврора"),
}

ALL_WAKE_WORDS: tuple[str, ...] = tuple(word for names in WAKE_NAMES.values() for word in names)

_LEAD = r"(?:эй|окей|ок|слушай|а|hey|ok|okay|yo|listen)?[\s,]*"

ADDRESS = re.compile(
    rf"^\s*{_LEAD}(?:{'|'.join(ALL_WAKE_WORDS)})\b[\s,.!?—–-]*",
    re.IGNORECASE,
)

# то же самое, но не только в начале фразы: «слушай, юки, открой хром»
ADDRESS_ANY = re.compile(rf"\b(?:{'|'.join(ALL_WAKE_WORDS)})\b", re.IGNORECASE)

POLITE = re.compile(
    r"\b(?:пожалуйста|будь добр(?:а|ы)?|прошу тебя|прошу|давай[- ]?ка|давай|ну[- ]?ка|а ну|"
    r"please|i want you to|i need you to)\b[\s,]*",
    re.IGNORECASE,
)

FILLER = re.compile(r"\b(?:эм+|мм+|ну|значит|короче|uh+|um+|well)\b[\s,]*", re.IGNORECASE)

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Убирает обращение, вежливые обороты и лишние знаки, сохраняя регистр остатка."""
    cleaned = text.strip()
    if not cleaned:
        return ""

    # чистим по кругу: «Ну давай, Юки, громкость 40» — обращение всплывает
    # в начало только после удаления вводных слов
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = POLITE.sub("", cleaned)
        cleaned = FILLER.sub("", cleaned)
        cleaned = ADDRESS.sub("", cleaned)
        cleaned = _SPACES.sub(" ", cleaned).strip(" .,!?…—–-")

    return cleaned


_MARKDOWN = re.compile(r"[*_`#>|]+")
_LINKS = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿]")
_LIST_MARK = re.compile(r"^\s*[-–—•\d]+[.)]?\s+", re.MULTILINE)

# Иероглифы, кана и хангыль. Многоязычная модель нет-нет да и дописывает к
# русской фразе кусок на китайском — синтез читает его как бессмысленный набор
# звуков либо молчит на середине реплики. В речь такое пускать нельзя.
_FOREIGN_SCRIPT = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿가-힯！-｠]+"
)

# Латинское слово, приклеенное вплотную к русскому: «Чемoccupied занят». Так
# многоязычная модель роняет чужой токен в середину фразы. Русский язык слов
# впритык не склеивает, поэтому это всегда порча, а не название программы —
# «открой Chrome» отделено пробелом и не трогается.
_GLUED_LATIN = re.compile(r"(?<=[а-яё])[A-Za-z]{3,}")

# сколько символов имеет смысл озвучивать за раз (примерно полминуты речи)
SPEECH_LIMIT = 420


# Дежурные обороты службы поддержки. Семимиллиардная модель срывается в них при
# любом промпте, а звучат они как автоответчик, а не как живой человек рядом.
#
# Заменяются только законченные обороты целиком. Отдельные «вы», «вам», «ваш»
# здесь намеренно не трогаются: механическая подстановка «ты» ломает согласование
# — выходит «ты любите» и «твоя просьба выполнен». Вслух рассогласованная фраза
# звучит хуже, чем лишняя вежливость, поэтому обращение остаётся заботой промпта.
_FORMAL: tuple[tuple[Pattern[str], str], ...] = (
    (re.compile(r"\bчем\s+(?:я\s+)?(?:могу|может)\s+(?:вам\s+|тебе\s+)?помочь"
                r"(?:\s+(?:вам|тебе))?\b", re.I), "что делаем"),
    (re.compile(r"\bкак\s+я\s+могу\s+(?:вам\s+|тебе\s+)?помочь(?:\s+(?:вам|тебе))?\b", re.I),
     "что делаем"),
    (re.compile(r"\bздравствуйте\b", re.I), "привет"),
    (re.compile(r"\bдобро\s+пожаловать\b", re.I), "рада тебя видеть"),
    (re.compile(r"\bуважаемый(?:\s+пользователь)?\b", re.I), ""),
    (re.compile(r"\bваш\s+запрос\s+выполнен\b", re.I), "готово"),
    (re.compile(r"\bрада\s+(?:была\s+)?помочь\s+вам\b", re.I), "рада помочь"),
    (re.compile(r"\bесли\s+у\s+вас\s+(?:есть\s+)?(?:ещё\s+)?вопросы[^.!?]*[.!?]", re.I), ""),
    (re.compile(r"\bобращайтесь\b", re.I), "зови"),
)


# первая буква предложения после точки, восклицательного или вопросительного знака
_SENTENCE_START = re.compile(r"(?<=[.!?]\s)[а-яёa-z]")


def soften(text: str) -> str:
    """Убирает дежурные обороты службы поддержки, не трогая согласование фразы."""
    result = text
    for pattern, replacement in _FORMAL:
        result = pattern.sub(replacement, result)
    result = _SPACES.sub(" ", result).strip(" ,;:")
    if not result:
        return result
    # заглавная буква могла уехать вместе с заменённым оборотом
    result = _SENTENCE_START.sub(lambda m: m.group(0).upper(), result)
    return result[:1].upper() + result[1:]


# Как читать вслух то, что написано латиницей.
#
# Синтез читает латинские слова по своим правилам и промахивается на названиях
# и аббревиатурах. Список пуст по умолчанию — заполняется под конкретный проект
# (свои бренды, каналы, термины), где буквальное чтение звучит криво.
#
# Правится только речь. На экране остаётся латинское написание — оно и есть
# фирменное; подменять его кириллицей в тексте нельзя.
_SPOKEN_AS: tuple[tuple[Pattern[str], str], ...] = ()


def as_spoken(text: str) -> str:
    """Заменяет латинские названия на то, как они произносятся по-русски."""
    result = text
    for pattern, sound in _SPOKEN_AS:
        result = pattern.sub(sound, result)
    return result


def clean_reply(text: str) -> str:
    """Чистит реплику от всего, что не должно доходить до человека.

    Тем же путём идут и субтитры, и журнал: иначе на экране оставался кусок на
    китайском, которого она вслух не произносила, — и запись разговора расходилась
    с тем, что человек слышал.
    """
    cleaned = soften(text)
    cleaned = _LINKS.sub("ссылка", cleaned)
    cleaned = _EMOJI.sub("", cleaned)
    cleaned = _FOREIGN_SCRIPT.sub("", cleaned)
    cleaned = _GLUED_LATIN.sub("", cleaned)
    cleaned = _MARKDOWN.sub("", cleaned)
    cleaned = _LIST_MARK.sub("", cleaned)
    return _SPACES.sub(" ", cleaned).strip(" ,;:")


def for_speech(text: str) -> str:
    """Готовит текст к синтезу: без markdown, ссылок и эмодзи — их движок читает как мусор."""
    # произношение правится только здесь, на пути в синтез: на экране бренд
    # обязан остаться латиницей
    cleaned = as_spoken(clean_reply(text))
    if len(cleaned) > SPEECH_LIMIT:
        cut = cleaned[:SPEECH_LIMIT]
        stop = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        cleaned = cut[: stop + 1] if stop > SPEECH_LIMIT // 2 else cut
    return cleaned


def addressed(text: str) -> bool:
    """Была ли фраза обращением к ассистенту по имени."""
    return bool(ADDRESS.match(text.strip())) or wake_name(text) is not None


def wake_name(text: str, cutoff: float = 0.86) -> str | None:
    """Ключ голоса, чьим именем позвали: jarvis, atlas или aura.

    Распознавание регулярно коверкает имя («джарис», «атлаз», «Джар вис»), поэтому
    первые слова фразы дополнительно сравниваются с именами по похожести. Иначе
    ассистент молча игнорирует обращение, и кажется, что он «не отвечает».
    """
    import difflib

    cleaned = re.sub(r"[^\w\s]", " ", str(text or "").lower())
    words = [word for word in cleaned.split() if len(word) > 2][:4]
    if not words:
        return None

    # склеенные варианты: «джар вис» → «юки»
    candidates = list(words) + [words[index] + words[index + 1] for index in range(len(words) - 1)]

    for key, names in WAKE_NAMES.items():
        for candidate in candidates:
            if candidate in names:
                return key
            if difflib.get_close_matches(candidate, names, n=1, cutoff=cutoff):
                return key
    return None


def strip_wake(text: str) -> str:
    """Убирает обращение из фразы, даже если имя расслышано с ошибкой."""
    cleaned = ADDRESS.sub("", text.strip(), count=1)
    if cleaned != text.strip():
        return cleaned.strip(" ,.!?—–-")

    key = wake_name(text)
    if key is None:
        return text.strip()

    words = text.strip().split()

    def plain(word: str) -> str:
        return re.sub(r"[^\w]", "", word).lower()

    # сначала пара слов: «Джар вис» — имя, разорванное распознаванием надвое
    for index in range(min(3, max(0, len(words) - 1))):
        if wake_name(plain(words[index]) + plain(words[index + 1])) == key:
            return " ".join(words[index + 2 :]).strip(" ,.!?—–-")
    for index, word in enumerate(words[:4]):
        if wake_name(plain(word)) == key:
            return " ".join(words[index + 1 :]).strip(" ,.!?—–-")
    return text.strip()
