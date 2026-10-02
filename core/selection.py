"""Действия с выделенным текстом в любой программе.

Выделил абзац в браузере, письме или документе — и сказал: «Юки, переведи это»,
«объясни», «перепиши вежливее», «исправь ошибки», «сократи». Юки копирует
выделение (Ctrl+C в том окне, где оно сделано), отвечает голосом и карточкой,
а на «замени» ставит готовый текст на место выделенного (Ctrl+V). Прежнее
содержимое буфера обмена возвращается на место.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from . import automation
from . import windows as win

_TARGET = r"(?:эт(?:о|от|у|и)\s*(?:текст|абзац|фрагмент|кусок|сообщени\w*)?|выделенн\w*(?:\s+текст\w*)?|выделение)"
MODES: dict[str, re.Pattern[str]] = {
    "translate": re.compile(rf"\b(?:переведи|перевести|перевод)\b.*{_TARGET}|{_TARGET}.*\bпереведи", re.I),
    "explain": re.compile(rf"\b(?:объясни|растолкуй|поясни|что\s+значит|что\s+означает)\b.*{_TARGET}", re.I),
    "polite": re.compile(rf"\b(?:перепиши|переделай|сделай)\b.*{_TARGET}.*\b(?:вежлив\w*|мягч\w*|официальн\w*|культурн\w*)"
                         rf"|\b(?:перепиши|переделай|сделай)\b.*\b(?:вежлив\w*|мягч\w*|официальн\w*)\b.*{_TARGET}", re.I),
    # «исправь эту ошибку» — это про код на экране, а не про выделенный текст:
    # здесь нужен признак текста (выделенное, текст, абзац, орфография…)
    "fix": re.compile(r"\b(?:исправь|проверь|поправь)\b.*\b(?:выделенн\w*|выделение|текст\w*|абзац\w*|фрагмент\w*|"
                      r"сообщени\w*|орфографи\w*|грамматик\w*|опечатк\w*|пунктуаци\w*)", re.I),
    "shorten": re.compile(rf"\b(?:сократи|укороти|перескажи\s+кратко|сделай\s+короче|выжимк\w*)\b.*{_TARGET}", re.I),
    "rewrite": re.compile(rf"\b(?:перепиши|переделай|улучши|перефразируй)\b.*{_TARGET}", re.I),
}
_REPLACE = re.compile(r"^(?:юки[,\s]+)?(?:замени|вставь|поставь|подставь)(?:\s+(?:это|его|текст|на\s+место|туда))*[.!]?$", re.I)
_TTL_S = 300.0

PROMPTS = {
    "translate": "Переведи текст. Если он на русском — на английский, иначе — на русский. Сохрани тон и форматирование. "
                 "Ответ — только перевод, без пояснений.",
    "explain": "Объясни простыми словами, что значит этот текст и о чём он. Первая строка — суть одной-двумя фразами "
               "для голоса, затем пустая строка и подробности в markdown, если нужны.",
    "polite": "Перепиши текст вежливее и спокойнее, сохранив смысл, язык и обращение оригинала (на «ты» — так и оставь). "
              "Ответ — только новый текст.",
    "fix": "Исправь орфографию, пунктуацию и грамматику, не меняя смысл, стиль и язык. Ответ — только исправленный текст.",
    "shorten": "Сократи текст в два-три раза, сохранив главное и язык оригинала. Ответ — только сокращённый текст.",
    "rewrite": "Перепиши текст яснее и живее, сохранив смысл и язык оригинала. Ответ — только новый текст.",
}
SPOKEN = {"translate": "Перевод", "polite": "Вежливый вариант", "fix": "Исправленный текст",
          "shorten": "Коротко", "rewrite": "Новый вариант"}


@dataclass
class Result:
    hwnd: int
    mode: str
    text: str
    at: float = field(default_factory=time.monotonic)


_lock = threading.Lock()
_last: Result | None = None


def mode_of(text: str) -> str | None:
    """Какое действие просят сделать с выделенным: translate, explain, polite, fix, shorten, rewrite."""
    for mode, pattern in MODES.items():
        if pattern.search(str(text or "")):
            return mode
    return None


class SelectionError(RuntimeError):
    """Выделить нечего или окно не отдало текст."""


def grab() -> tuple[str, int]:
    """Копирует выделение из окна, где человек работает. Возвращает текст и окно."""
    from . import replies

    window = replies.target_window()
    if window is None:
        raise SelectionError("не вижу окна с текстом")
    previous = automation.get_clipboard()
    marker = f"⁣yuki-{time.monotonic()}"
    automation.set_clipboard(marker)
    try:
        win.focus(window)
        time.sleep(0.15)
        automation.press_hotkey(("ctrl", "c"))
        text = ""
        for _ in range(12):
            time.sleep(0.05)
            text = automation.get_clipboard() or ""
            if text and text != marker:
                break
    finally:
        if previous is not None:
            automation.set_clipboard(previous)
    if not text or text == marker or not text.strip():
        raise SelectionError("сначала выдели текст, а потом попроси")
    return text.strip()[:6000], int(window.hwnd)


def remember(hwnd: int, mode: str, text: str) -> None:
    global _last
    with _lock:
        _last = Result(hwnd, mode, text)


def wants_replace(text: str) -> bool:
    """«Замени», «вставь» — к последнему результату, если он свежее вариантов ответа собеседнику."""
    from . import replies

    with _lock:
        last = _last
    if last is None or time.monotonic() - last.at > _TTL_S or last.mode == "explain":
        return False
    suggestion = replies.pending()
    if suggestion is not None and suggestion.at > last.at:
        return False  # последним было «что мне ему ответить» — «вставь» относится к нему
    return bool(_REPLACE.match(str(text or "").strip()))


def replace() -> str:
    """Ставит готовый текст на место выделенного в том же окне."""
    global _last
    with _lock:
        result = _last
        _last = None
    if result is None:
        raise SelectionError("нечего вставлять")
    target = next((item for item in win.enumerate_windows() if int(item.hwnd) == result.hwnd), None)
    if target is None:
        raise SelectionError("окно с текстом уже закрыто")
    previous = automation.get_clipboard()
    automation.set_clipboard(result.text)
    try:
        win.focus(target)
        time.sleep(0.15)
        automation.press_hotkey(("ctrl", "v"))
        time.sleep(0.25)
    finally:
        if previous is not None:
            automation.set_clipboard(previous)
    return "Заменила."
