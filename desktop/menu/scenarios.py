"""Раздел «Сценарии»: несколько действий под одним именем, запуск в одно нажатие.

Страница нарочно показывает шаги целиком. Сценарий, который делает что-то
невидимое, доверия не вызывает: человек должен видеть, что именно произойдёт,
прежде чем нажмёт.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import i18n, workflows

from .controls import Card


class _Runner(QObject):
    done = Signal(str)

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def run(self) -> None:
        try:
            self.done.emit(workflows.run(self._name).report())
        except Exception as err:  # noqa: BLE001 — показываем человеку как есть
            self.done.emit(f"Не выполнилось: {err}")


class ScenariosPage(QWidget):
    """Список сценариев с кнопкой запуска у каждого."""

    speak = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._runner: _Runner | None = None
        self._buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        card = Card(
            i18n.t("Сценарии"),
            i18n.t("Одна фраза — несколько действий. Скажите «Юки, рабочий режим» или нажмите здесь."),
        )
        for item in workflows.catalog():
            card.add(self._row(item))
        layout.addWidget(card)

        self.status = QLabel(i18n.t("Выберите сценарий."))
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)

    def _row(self, item: workflows.Workflow) -> QWidget:
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 6, 0, 6)
        line.setSpacing(16)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        title = QLabel(item.title)
        title.setObjectName("rowLabel")
        steps = QLabel(" → ".join(step.describe() for step in item.steps))
        steps.setObjectName("rowHint")
        steps.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(steps)

        button = QPushButton(i18n.t("Запустить"))
        button.setObjectName("menuAction")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _=False, name=item.name: self._start(name))
        self._buttons.append(button)

        line.addLayout(text, 1)
        line.addWidget(button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return holder

    def _start(self, name: str) -> None:
        if self._thread is not None:
            return
        self.status.setText(f"Выполняю «{name}»…")
        for button in self._buttons:
            button.setEnabled(False)

        thread = QThread(self)
        runner = _Runner(name)
        runner.moveToThread(thread)
        thread.started.connect(runner.run)

        def finish(report: str) -> None:
            thread.quit()
            thread.wait(2000)
            self._thread, self._runner = None, None
            for button in self._buttons:
                button.setEnabled(True)
            self.status.setText(report)
            self.speak.emit(report)

        runner.done.connect(finish)
        self._thread, self._runner = thread, runner
        thread.start()
