"""Эмоция реплики: во что персонаж меняется в лице, когда говорит именно это.

Раньше персонаж реагировал не на смысл, а на тип события: любой ответ ассистента
одинаково включал «говорит», и лицо было одним и тем же и для шутки, и для отказа,
и для «не могу найти файл». Здесь реплика разбирается по словам и превращается в
ключ эмоции — тот же набор, что понимает аниматор.

Разбор нарочно словарный, без модели: он вызывается на каждой фразе, и лишние
полсекунды на видеокарте здесь стоили бы дороже, чем даёт точность.
"""

from __future__ import annotations

import re
from typing import Final

# ключи должны совпадать с desktop/companion/emotions.py
NEUTRAL: Final = "neutral"

# порядок важен: первое совпадение выигрывает, поэтому вверху — самые определённые
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "sad",
        re.compile(
            r"\b(?:не\s+смог\w*|не\s+получилось|не\s+нашл\w+|не\s+удалось|не\s+вышло|"
            r"ошибк\w+|сбой|прости\w*|извини\w*|жаль|сочувству\w+|грустно|печал\w+|"
            r"соболезн\w+|увы)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "surprised",
        re.compile(
            r"(?:\bого\b|\bничего\s+себе\b|\bсерьёзно\b|\bсерьезно\b|\bвот\s+это\b|"
            r"\bправда\?|\bнеужели\b|\bда\s+ладно\b|\bвау\b|\bпредставь\b|\bкак\s+так\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "joy",
        re.compile(
            r"(?:\bура\b|\bотлично\b|\bсупер\b|\bкласс\b|\bздорово\b|\bпоздравля\w+|"
            r"\bура!|\bхаха\b|\bсмешн\w+|\bобожаю\b|\bлюблю\b|!{2,})",
            re.IGNORECASE,
        ),
    ),
    (
        "shy",
        re.compile(
            r"(?:\bспасибо\b|\bблагодар\w+|\bсмущ\w+|\bкраснею\b|\bты\s+чего\b|"
            r"\bперестань\b|\bда\s+ну\s+тебя\b|\bмиленьк\w+|\bприятно\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "greeting",
        re.compile(
            r"^\s*(?:привет|здравствуй|доброе\s+утро|добрый\s+(?:день|вечер)|хай|"
            r"снова\s+тут|рада\s+(?:тебя\s+)?(?:видеть|слышать))",
            re.IGNORECASE,
        ),
    ),
    (
        "wink",
        re.compile(
            r"(?:\bконечно\b|\bразумеется\b|\bлегко\b|\bпустяк\w*|\bкак\s+скажешь\b|"
            r"\bбез\s+проблем\b|\bуже\s+сделал\w*|\bдержи\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "thinking",
        re.compile(
            r"(?:\bсейчас\s+посмотрю\b|\bминутку\b|\bсекунд\w+|\bпогоди\b|\bдай\s+подумать\b|"
            r"\bне\s+уверен\w*|\bкажется\b|\bвозможно\b|\bнаверн\w+)",
            re.IGNORECASE,
        ),
    ),
    (
        "happy",
        re.compile(
            r"(?:\bготово\b|\bсделал\w*|\bоткрыл\w*|\bзапустил\w*|\bвключил\w*|\bнашл\w+|"
            r"\bотправил\w*|\bзаписал\w*|\bзапомнил\w*)",
            re.IGNORECASE,
        ),
    ),
)

# Как эмоция называется у плоского (рисованного) персонажа и у трёхмерного.
# Справа только ключи из EXPRESSIONS в ui3d/js/behaviour.js: неизвестное имя
# трёхмерный персонаж молча игнорирует, и лицо остаётся каменным.
FLAT_TO_3D: Final[dict[str, str]] = {
    "neutral": "calm",
    "happy": "happy",
    "joy": "happy",
    "surprised": "surprised",
    "thinking": "thinking",
    "listening": "attentive",
    "speaking": "smile",
    "shy": "smile",
    "sad": "sad",
    "wink": "smile",
    "greeting": "happy",
    "alert": "sad",
}


def of(text: str) -> str:
    """Ключ эмоции для реплики. Ничего характерного не нашлось — «говорит»."""
    clean = (text or "").strip()
    if not clean:
        return NEUTRAL
    for key, pattern in _RULES:
        if pattern.search(clean):
            return key
    if clean.count("?") and len(clean) < 90:
        return "listening"  # встречный вопрос — заинтересованный взгляд
    return "speaking"


def dimensional(key: str) -> str:
    """Имя той же эмоции в наборе трёхмерного персонажа."""
    return FLAT_TO_3D.get(key, "smile")
