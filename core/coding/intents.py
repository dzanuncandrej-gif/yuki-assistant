"""Фразы, по которым Юки понимает, что нужен агент-программист."""

from __future__ import annotations

import re

# «напиши код калькулятора», «создай проект игры змейка», «сделай сайт», «запрограммируй»
ASK = re.compile(
    r"(?:напиши|написать|создай|создать|сделай|сделать|запрограммируй|разработай|накодь|закодь)\s+"
    r"(?:мне\s+|нам\s+)?(?:(?:на\s+\w+\s+)?(?:питоне|python|js|javascript|html)\s+)?"
    r"(?:код\w*|программ\w*|проект\w*|приложени\w*|игр\w*|сайт\w*|скрипт\w*|калькулятор\w*|бот\w*|утилит\w*|"
    r"змейк\w*|тетрис\w*|страниц\w*|лендинг\w*)"
    r"|(?:мне\s+)?(?:надо|нужно)\s+(?:написать|создать|сделать)\s+(?:\w+\s+){0,2}(?:проект|программ|код|игр|сайт|приложени)",
    re.IGNORECASE,
)
_NOT_CODE = re.compile(r"напиши\s+(?:сообщени|в\s+(?:телеграм|чат|избранное)|маме|папе|ему|ей)", re.IGNORECASE)
_CHANGE = re.compile(
    r"^(?:юки[,\s]+)?(?:доработай|добавь|измени|поменяй|переделай|улучши|убери|допиши|исправь|сделай)\b",
    re.IGNORECASE,
)
_PROJECT_WORDS = re.compile(
    r"\b(?:в\s+(?:проект\w*|программ\w*|приложени\w*|код\w*|игр\w*|сайт\w*)|туда|в\s+не[её]|в\s+него|"
    r"доработай(?:\s+(?:его|её|проект|программу))?$)",
    re.IGNORECASE,
)


def wants_code(text: str) -> bool:
    text = str(text or "")
    return bool(ASK.search(text)) and not _NOT_CODE.search(text)


def wants_change(text: str, title: str = "") -> bool:
    """«Добавь в калькулятор тёмную тему», «доработай змейку: уровни» — правка последнего проекта."""
    text = str(text or "").strip()
    if not _CHANGE.search(text) or _NOT_CODE.search(text):
        return False
    if _PROJECT_WORDS.search(text) or re.match(r"^(?:юки[,\s]+)?доработай\b", text, re.IGNORECASE):
        return True
    stem = title.lower()[:5] if len(title) >= 5 else title.lower()
    return bool(stem) and stem in text.lower()
