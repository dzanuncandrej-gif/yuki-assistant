"""Сборка десктопного приложения: формат OpenGL, ассистент, мост, окно."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from core import autostart, bus
from core.assistant import Assistant

from . import webassets
from .bridge import Bridge
from .shell import Shell
from .theme import QSS
from .window import MainWindow


def _configure_opengl() -> None:
    """Ядро OpenGL 3.3: нужно встроенной сцене персонажа и сглаживанию панелей."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)   # сцене персонажа нужен буфер глубины
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)


_GREETINGS: tuple[str, ...] = (
    "Привет, {name}! Я тут. Чем займёмся?",
    "О, {name}, привет! Скучала. Что делаем?",
    "Привет! Я на месте, {name}. Говори, что нужно.",
    "С возвращением, {name}. Я вся внимание.",
    "Привет-привет! Ну что, {name}, с чего начнём?",
)


def _greeting(cfg: Mapping[str, Any]) -> str:
    """Приветствие при запуске.

    Каждый раз разное и на «ты»: одна и та же казённая фраза при каждом запуске
    первым делом сообщала, что рядом программа, а не собеседница.
    """
    import random

    name = str(cfg.get("account", {}).get("name", "")).strip()
    line = random.choice(_GREETINGS)
    if not name:
        return line.replace(", {name}", "").replace("{name}, ", "").replace("{name}", "").replace(" !", "!")
    return line.format(name=name)


def run(cfg: Mapping[str, Any], selftest: Path | None = None) -> int:
    _configure_opengl()
    # схему ассетов персонажа Chromium запоминает один раз — до создания приложения
    webassets.register_scheme()

    app = QApplication(sys.argv)
    app.setApplicationName("Юки")
    app.setQuitOnLastWindowClosed(False)  # живём в трее
    app.setStyleSheet(QSS)

    # настройка автозапуска могла измениться вне приложения — приводим в согласие
    autostart.sync(bool(cfg.get("ui", {}).get("autostart", False)))

    assistant = Assistant(cfg)
    bridge = Bridge()
    bus.bus.subscribe_callback(bridge.publish)

    shell = Shell(assistant, bridge, cfg)
    window = MainWindow(assistant, bridge, shell)
    window.show()

    if selftest is not None:
        _schedule_selftest(window, selftest, app)
    else:
        assistant.start()
        shell.start()
        assistant.greet(_greeting(cfg))

    return app.exec()


def _schedule_selftest(window: MainWindow, target: Path, app: QApplication) -> None:
    """Снимает каждый раздел пульта — проверка сборки без запуска микрофона."""

    sections = ("dialog", "voice", "ai", "character", "account")

    def capture() -> None:
        window.log.add_message("system", "Самопроверка интерфейса.")
        window.log.add_message("user", "открой блокнот")
        window.log.add_message("assistant", "Запускаю блокнот.")
        _shoot(0)

    def _shoot(index: int) -> None:
        if index >= len(sections):
            app.quit()
            return
        section = sections[index]
        window.open_section(section)

        def save() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            path = target.with_name(f"{target.stem}_{section}.png")
            window.grab().save(str(path))
            print(f"selftest: сохранено {path}")
            _shoot(index + 1)

        QTimer.singleShot(900, save)

    QTimer.singleShot(1200, capture)
