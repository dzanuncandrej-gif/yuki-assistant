"""Быстрое зрение: поиск надписи в OCR, выжимка экрана, маршрутизация вопросов."""

from __future__ import annotations

from core import live, ocr


def _reading(*rows: tuple[str, tuple[int, int, int, int]]) -> ocr.Reading:
    return ocr.Reading(lines=tuple(ocr.Line(text, rect) for text, rect in rows), at=0.0, spent_ms=1.0)


def test_find_prefers_exact_label() -> None:
    reading = _reading(("Сохранить как", (0, 0, 100, 20)), ("Сохранить", (10, 40, 90, 60)))
    line = ocr.find("сохранить", reading)
    assert line is not None and line.text == "Сохранить"
    assert line.center == (50, 50)


def test_find_rejects_unrelated_text() -> None:
    reading = _reading(("Настройки профиля", (0, 0, 100, 20)))
    assert ocr.find("отправить", reading) is None


def test_compact_drops_duplicates_and_noise() -> None:
    reading = _reading(("Файл", (0, 0, 1, 1)), ("файл", (0, 0, 1, 1)), ("|", (0, 0, 1, 1)), ("Правка", (0, 0, 1, 1)))
    assert reading.compact() == "Файл | Правка"


def test_sense_digest_mentions_window_dialog_and_text() -> None:
    sensed = live.Sense(app="code.exe", title="main.py", dialog="Ошибка сборки",
                        text="Traceback (most recent call last): File main.py, line 3, in <module> "
                             "import requests. ImportError: No module named requests. Process finished.", at=1.0)
    digest = sensed.digest()
    assert "main.py" in digest and "Ошибка сборки" in digest and "ImportError" in digest
    assert not sensed.sparse


def test_screen_questions_are_routed() -> None:
    assert live.asks_about_screen("что у меня на экране")
    assert live.asks_about_screen("что это за ошибка")
    # «объясни» без экрана — это вопрос к знаниям, а не к экрану
    assert not live.asks_about_screen("объясни, как работает нейросеть")
    assert live.needs_pixels("какого цвета кнопка")
    assert not live.needs_pixels("что тут написано")
