"""Фоновые шаги интерфейса не должны трогать виджеты из чужого потока.

Из-за этого окно зависало и закрывалось: сигнал рабочего потока приходил в
свободную функцию, у которой нет своего потока, Qt выполнял её прямо в рабочем
потоке — там же обновлялись надписи и там же поток ждал сам себя.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="тесты интерфейса требуют PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    yield existing or QApplication([])


def test_background_job_returns_to_the_gui_thread(app) -> None:
    from desktop.menu.messages import MessagesPage

    page = MessagesPage()
    gui_thread = threading.current_thread().name
    seen: dict[str, object] = {}

    def job() -> object:
        seen["job_thread"] = threading.current_thread().name
        time.sleep(0.2)
        return "готово"

    def done(result: object, error: str) -> None:
        seen["done_thread"] = threading.current_thread().name
        seen["result"] = result
        seen["error"] = error
        app.quit()

    page._run(job, done)
    QTimer.singleShot(10_000, app.quit)   # страховка, чтобы тест не висел вечно
    app.exec()

    assert seen.get("job_thread") not in (None, gui_thread), "долгий шаг остался в потоке интерфейса"
    assert seen["done_thread"] == gui_thread, "итог пришёл не в поток интерфейса — окно так и падало"
    assert seen["result"] == "готово"
    assert seen["error"] == ""


def test_page_is_idle_again_after_the_job(app) -> None:
    from desktop.menu.messages import MessagesPage

    page = MessagesPage()
    page._run(lambda: "ок", lambda result, error: app.quit())
    QTimer.singleShot(10_000, app.quit)
    app.exec()
    assert page._thread is None, "страница осталась занятой — вторая попытка была бы заблокирована"
