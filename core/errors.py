"""Ошибки — человеческими словами, а не простынёй из Windows."""

from __future__ import annotations

import requests


def friendly(err: BaseException) -> str:
    """Короткая понятная причина для голоса и интерфейса."""
    if isinstance(err, requests.Timeout):
        return "модель думала слишком долго и не ответила"
    if isinstance(err, (requests.ConnectionError, ConnectionError)):
        return "пропала связь с моделью — Ollama перезапускается, повтори через минуту"
    if isinstance(err, requests.HTTPError):
        return "модель отказалась отвечать (ошибка Ollama)"
    text = str(err).strip().splitlines()[0] if str(err).strip() else err.__class__.__name__
    return text[:160]
