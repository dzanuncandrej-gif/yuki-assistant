"""Панель быстрого запуска: часто нужные программы в один клик.

Своего механизма запуска здесь нет. Кнопка делает ровно то же, что и голосовая
команда «открой …»: зовёт `core.apps.launch`. Поэтому список работает с любой
программой, которую Юки и так умеет открывать, и ведёт себя одинаково — что
голосом, что мышью.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QWidget

from core import apps, bus, i18n

from .controls import Card
from .settings import SettingsStore

# чем пользуются чаще всего; список правится прямо в панели
DEFAULTS: tuple[str, ...] = (
    "Telegram", "Steam", "Chrome", "Проводник", "Блокнот", "Калькулятор",
)
MAX_TILES = 12
COLUMNS = 3


def launch(name: str) -> None:
    """Запуск в фоне: открытие программы блокирует поток на секунды."""

    def run() -> None:
        try:
            apps.launch(name)
            bus.bus.log("system", f"Запускаю {name}.")
        except Exception as err:
            bus.bus.log("error", f"Не удалось открыть {name}: {err}")

    threading.Thread(target=run, name=f"quick-{name}", daemon=True).start()


def _tile(name: str, on_click: Callable[[str], None], on_remove: Callable[[str], None]) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)

    button = QPushButton(name)
    button.setObjectName("menuAction")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumHeight(38)
    button.clicked.connect(lambda: on_click(name))

    remove = QPushButton("✕")
    remove.setObjectName("menuGhost")
    remove.setFixedSize(28, 38)
    remove.setToolTip(i18n.t("Убрать {name} из панели").format(name=name))
    remove.setCursor(Qt.CursorShape.PointingHandCursor)
    remove.clicked.connect(lambda: on_remove(name))

    row.addWidget(button, 1)
    row.addWidget(remove)
    return holder


def quick_launch_card(store: SettingsStore) -> Card:
    """Карточка с плитками. Список хранится в настройках и переживает перезапуск."""
    card = Card(i18n.t("Быстрый запуск"), i18n.t("Часто нужные программы. То же самое, что сказать «открой …»."))

    grid_holder = QWidget()
    grid = QGridLayout(grid_holder)
    grid.setContentsMargins(0, 4, 0, 4)
    grid.setSpacing(6)
    card.add(grid_holder)

    def items() -> list[str]:
        saved = store.get("quick_launch", "apps", None)
        return [str(x) for x in saved] if isinstance(saved, list) else list(DEFAULTS)

    def save(values: list[str]) -> None:
        store.set("quick_launch", "apps", values[:MAX_TILES])
        rebuild()

    def remove(name: str) -> None:
        save([x for x in items() if x != name])

    def add() -> None:
        name = field.text().strip()
        if not name:
            return
        field.clear()
        current = items()
        if name.lower() not in {x.lower() for x in current}:
            save([*current, name])

    def rebuild() -> None:
        while grid.count():
            child = grid.takeAt(0).widget()
            if child is not None:
                child.deleteLater()
        for index, name in enumerate(items()):
            grid.addWidget(_tile(name, launch, remove), index // COLUMNS, index % COLUMNS)

    field = QLineEdit()
    field.setPlaceholderText(i18n.t("Добавить программу — Enter"))
    field.returnPressed.connect(add)

    adder = QWidget()
    row = QHBoxLayout(adder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(field, 1)
    button = QPushButton(i18n.t("ДОБАВИТЬ"))
    button.setObjectName("menuGhost")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(add)
    row.addWidget(button)
    card.add(adder)

    rebuild()
    return card
