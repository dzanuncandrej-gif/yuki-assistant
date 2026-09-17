"""Исправление расслышанных слов по словарю команд.

Распознавание регулярно ошибается на безударных гласных и удвоенных согласных:
«Джорвис», «телеграммы», «громкасть», «скрыншот». Для человека это одно и то же слово,
для шаблонов команд — уже нет, и команда молча не срабатывает.

Здесь слова приводятся к «звуковой» форме (безударные гласные сводятся к одной, двойные
согласные схлопываются) и сравниваются со словарём команд. Свободный текст — то, что
идёт после «напиши», «найди», «введи» — не трогается: там человек говорит что угодно.
"""

from __future__ import annotations

import difflib
import re
from functools import lru_cache

# слова, после которых начинается произвольный текст — его исправлять нельзя
FREE_TAIL = re.compile(
    r"\b(?:напиши|напечатай|набери|введи|отправь|передай|скажи|сообщи|найди|поищи|погугли|"
    r"запиши|запомни|создай\s+файл|с\s+текстом|сообщение|текст|type|write|send|search|"
    # после «песню», «видео» идёт название — «Скриптонит» нельзя «исправлять» в ярлык
    r"песн\w*|трек\w*|музык\w*|видео|ролик\w*|клип\w*|фильм\w*|поставь|вруби|ютуб\w*)\b",
    re.IGNORECASE,
)

# ядро словаря: команды, приложения, единицы. Дополняется именами голосов и ярлыков.
BASE_WORDS: tuple[str, ...] = (
    # обращение
    "юки", "атлас", "аура",
    # действия
    "открой", "открыть", "запусти", "запустить", "включи", "выключи", "закрой", "заверши",
    "сверни", "разверни", "переключись", "покажи", "прочитай", "создай", "удали", "скопируй",
    "перемести", "переименуй", "нажми", "кликни", "прокрути", "поставь", "сделай", "проверь",
    "посмотри", "расскажи", "объясни", "повтори", "продолжи", "останови", "хватит", "стоп",
    "замолчи", "отмена", "напомни",
    # объекты системы
    "громкость", "яркость", "звук", "музыку", "музыка", "трек", "песню", "скриншот", "снимок",
    "экран", "экране", "окно", "окна", "папку", "папка", "файл", "файлы", "рабочем", "столе",
    "документы", "загрузки", "корзину", "буфер", "процесс", "компьютер", "систему", "память",
    "диск", "диски", "батарея", "время", "дата", "погода", "погоду", "новости", "интернете",
    "браузер", "вкладку", "голос", "голоса", "напоминание", "таймер",
    # приложения
    "телеграм", "телеграмм", "вотсап", "дискорд", "хром", "гугл", "ютуб", "яндекс", "стим",
    "блокнот", "калькулятор", "проводник", "настройки", "параметры", "терминал", "спотифай",
    "фотошоп", "ворд", "эксель", "код", "браузере",
    # частицы, которые важны для шаблонов
    "процентов", "сейчас", "сегодня", "завтра", "минут", "секунд", "часов",
)

# гласные, которые распознавание путает в безударной позиции, плюс оглушение согласных
# на конце слова: «Атлаз» и «Атлас» на слух не различаются
_FOLD = str.maketrans(
    {
        "о": "а", "ы": "и", "э": "е", "ё": "е", "я": "а", "ю": "у", "й": "и",
        "з": "с", "д": "т", "б": "п", "в": "ф", "г": "к", "ж": "ш",
    }
)
_DOUBLE = re.compile(r"(.)\1+")
_WORD = re.compile(r"[а-яёa-z]+", re.IGNORECASE)

# падежные окончания: их наличие не повод менять слово на словарное
_ENDINGS = frozenset(
    ("", "а", "у", "е", "и", "ы", "я", "ю", "ой", "ом", "ем", "ах", "ям", "ам", "ов", "ей", "ью")
)

_extra: set[str] = set()


def teach(words: object) -> None:
    """Добавляет слова в словарь: имена голосов, ярлыки приложений, контакты."""
    if isinstance(words, str):
        words = [words]
    for word in words or ():
        clean = str(word).strip().lower()
        if len(clean) > 2 and _WORD.fullmatch(clean):
            _extra.add(clean)
    _vocabulary.cache_clear()


@lru_cache(maxsize=1)
def _vocabulary() -> tuple[dict[str, str], tuple[str, ...], frozenset[str]]:
    """Звуковая форма → слово, список форм для нечёткого поиска и точные написания.

    Точные написания нужны отдельно: «окна» и «окно» звучат одинаково, и без этой
    проверки правильное слово подменялось бы соседним из словаря.
    """
    table: dict[str, str] = {}
    literal: set[str] = set()
    for word in (*BASE_WORDS, *sorted(_extra)):
        table.setdefault(sound(word), word)
        literal.add(word)
    return table, tuple(table), frozenset(literal)


def sound(word: str) -> str:
    """Звуковая форма слова: безударные гласные сведены, двойные буквы схлопнуты."""
    folded = str(word).lower().translate(_FOLD)
    return _DOUBLE.sub(r"\1", folded)


def correct_word(word: str, cutoff: float = 0.8) -> str:
    """Одно слово: возвращает словарное написание, если оно достаточно похоже."""
    lowered = word.lower()
    if len(lowered) < 3 or not _WORD.fullmatch(lowered):
        return word

    table, keys, literal = _vocabulary()
    if lowered in literal:
        return word  # слово и так правильное — «окна» не должно стать «окно»

    key = sound(lowered)
    exact = table.get(key)
    if exact is not None:
        return exact if exact != lowered else word

    match = difflib.get_close_matches(key, keys, n=1, cutoff=cutoff)
    if not match:
        return word
    candidate = table[match[0]]
    # не подменяем слово, если оно и так длиннее подсказки на пару букв — это другое слово
    if abs(len(candidate) - len(lowered)) > 3:
        return word
    # «Москве» и «Москва», «экрана» и «экран» — одно слово в разных падежах.
    # Общая основа плюс короткие разные хвосты означают падеж, а не ошибку слуха.
    prefix = len(_common_prefix(lowered, candidate))
    if prefix >= 4 and len(lowered) - prefix <= 2 and len(candidate) - prefix <= 2:
        return word
    if lowered.startswith(candidate) and lowered[len(candidate) :] in _ENDINGS:
        return word
    if candidate.startswith(lowered) and candidate[len(lowered) :] in _ENDINGS:
        return word
    return candidate


def _common_prefix(left: str, right: str) -> str:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return left[:index]


def correct(text: str) -> str:
    """Исправляет команду целиком, не трогая свободный текст после «напиши», «найди»…"""
    raw = str(text or "")
    if not raw.strip():
        return raw

    tail = FREE_TAIL.search(raw)
    head_end = tail.end() if tail else len(raw)
    head, rest = raw[:head_end], raw[head_end:]

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        fixed = correct_word(word)
        if fixed == word:
            return word
        return fixed.capitalize() if word[:1].isupper() else fixed

    return _WORD.sub(replace, head) + rest
