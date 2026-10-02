"""Командная строка поверх всех окон: Ctrl+Alt+Пробел.

Как Spotlight или Raycast: поле ввода по центру экрана, подсказки под ним.
Команда уходит Юки так же, как фраза голосом, а ответ показывается прямо здесь —
окно пульта открывать не нужно. Esc или щелчок мимо прячут строку. Окно, в
котором человек работал, остаётся «целевым»: «переведи выделенное» и «что мне
ему ответить» смотрят туда, а не на саму строку.
"""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from core import bus

from . import fonts

# (что ввести, подсказка) — частые и новые возможности, чтобы их было легко найти
SUGGESTIONS: tuple[tuple[str, str], ...] = (
    ("переведи выделенное", "перевод текста, выделенного в любой программе"),
    ("перепиши выделенное вежливее", "мягче и культурнее, потом «замени»"),
    ("исправь ошибки в выделенном тексте", "орфография и пунктуация"),
    ("объясни выделенное", "простыми словами"),
    ("что мне ему ответить", "три варианта ответа в открытом чате"),
    ("что мне писали", "кто и о чём писал в Telegram"),
    ("доброе утро", "погода, напоминания и сообщения"),
    ("включи мою музыку", "плейлист вперемешку"),
    ("что у меня на экране", "Юки смотрит на экран"),
    ("что за ошибка", "разбор ошибки в коде на экране"),
    ("напиши игру змейка", "агент пишет и проверяет проект"),
    ("какая погода на сегодня", ""),
    ("напомни через 10 минут проверить духовку", ""),
    ("громкость 30", ""),
    ("сделай скриншот", ""),
    ("давай созвонимся", "видеосвязь: Юки видит экран"),
)
_WIDTH = 680


class _Relay(QObject):
    reply = Signal(str, str)


class CommandPalette(QWidget):
    def __init__(self, assistant: Any) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._assistant = assistant
        self._waiting = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_WIDTH)
        self.setWindowTitle("Юки — команда")

        self.input = QLineEdit()
        self.input.setPlaceholderText("Скажи Юки, что сделать…  (Enter — выполнить, Esc — закрыть)")
        self.input.setFont(fonts.font(fonts.SANS, 15))
        self.input.setAccessibleName("Команда для Юки")
        self.input.textChanged.connect(self._filter)
        self.input.returnPressed.connect(self._run)
        self.input.installEventFilter(self)

        self.answer = QLabel()
        self.answer.setWordWrap(True)
        self.answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.answer.setFont(fonts.font(fonts.SANS, 11.5))
        self.answer.hide()

        self.list = QListWidget()
        self.list.setFont(fonts.font(fonts.SANS, 11))
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda item: self._use(item, run=True))
        self.list.setAccessibleName("Подсказки")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(self.input)
        layout.addWidget(self.answer)
        layout.addWidget(self.list)
        self.setStyleSheet("""
            QLineEdit { background: transparent; border: 0; color: #ffffff; padding: 6px 4px;
                        selection-background-color: #58b6ff; }
            QLabel { color: #dfe8f7; background: rgba(88, 140, 255, 0.10); border-radius: 12px; padding: 10px 12px; }
            QListWidget { background: transparent; border: 0; color: #b9c4d8; outline: none; }
            QListWidget::item { padding: 7px 10px; border-radius: 9px; }
            QListWidget::item:selected { background: rgba(88, 140, 255, 0.22); color: #ffffff; }
        """)

        self._relay = _Relay(self)
        self._relay.reply.connect(self._show_reply, Qt.ConnectionType.QueuedConnection)
        bus.bus.subscribe_callback(self._on_bus)
        self._filter("")

    # ---------------------------------------------------------------- показ

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
            return
        self.input.clear()
        self.answer.hide()
        self._filter("")
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center()) \
            or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.adjustSize()
        self.move(QPoint(area.center().x() - _WIDTH // 2, area.top() + int(area.height() * 0.22)))
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 20, 20)
        painter.fillPath(path, QColor(8, 12, 26, 242))
        border = QLinearGradient(0, 0, self.width(), 0)
        border.setColorAt(0, QColor(88, 182, 255, 200))
        border.setColorAt(1, QColor(139, 108, 255, 200))
        painter.setPen(QPen(border, 1.4))
        painter.drawPath(path)

    def changeEvent(self, event) -> None:
        # щелчок мимо — строка прячется, как у системного поиска
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and not self._waiting:
            self.hide()
        super().changeEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.list.count():
                row = self.list.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if key == Qt.Key.Key_Tab and self.list.currentItem() is not None:
                self._use(self.list.currentItem(), run=False)
                return True
        return super().eventFilter(watched, event)

    # ---------------------------------------------------------------- подсказки и запуск

    def _filter(self, text: str) -> None:
        query = text.strip().lower()
        self.list.clear()
        for command, hint in SUGGESTIONS:
            if query and query not in command and query not in hint.lower():
                continue
            item = QListWidgetItem(f"{command}" + (f"   ·   {hint}" if hint else ""))
            item.setData(Qt.ItemDataRole.UserRole, command)
            self.list.addItem(item)
            if self.list.count() >= 7:
                break
        self.list.setVisible(self.list.count() > 0 and not self._waiting)
        rows = sum(self.list.sizeHintForRow(index) for index in range(self.list.count()))
        self.list.setFixedHeight(rows + 8)
        self.adjustSize()

    def _use(self, item: QListWidgetItem, run: bool) -> None:
        self.input.setText(str(item.data(Qt.ItemDataRole.UserRole)))
        if run:
            self._run()

    def _run(self) -> None:
        text = self.input.text().strip()
        if not text and self.list.currentItem() is not None:
            text = str(self.list.currentItem().data(Qt.ItemDataRole.UserRole))
        if not text:
            return
        self._waiting = True
        self.list.hide()
        self.answer.setText("Юки думает…")
        self.answer.show()
        self.adjustSize()
        threading.Thread(target=self._assistant.handle_text, args=(text,), daemon=True,
                         name="yuki-palette").start()

    def _on_bus(self, event: dict) -> None:
        if self._waiting and event.get("type") == "message" and event.get("kind") in ("assistant", "report", "error"):
            self._relay.reply.emit(str(event.get("kind")), str(event.get("text") or ""))

    def _show_reply(self, kind: str, text: str) -> None:
        if kind == "assistant":
            self._waiting = False
        shown = text if len(text) < 900 else text[:900] + "…"
        current = self.answer.text()
        self.answer.setText(shown if current == "Юки думает…" or kind == "assistant" else f"{current}\n\n{shown}")
        self.answer.show()
        self.adjustSize()
