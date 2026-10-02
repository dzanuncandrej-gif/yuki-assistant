"""Вкладка «Агент»: Юки пишет проект, а здесь видно, как именно.

Слева — задача и ход работы по шагам, справа — файлы проекта и код. Пока
модель пишет, код появляется в окне строка за строкой. Голосом то же самое:
«Юки, напиши игру змейка» — вкладка откроется сама.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import bus, i18n
from core.coding import checks as coderun

from .. import fonts
from ..theme import ACCENT, TEXT
from .controls import Card

PAGE_QSS = f"""
QListWidget#agentSteps, QListWidget#agentFiles {{
    background: rgba(8, 13, 28, 0.55); border: 1px solid rgba(130, 170, 255, 0.14);
    border-radius: 14px; padding: 6px; color: {TEXT}; font-size: 12.5px; outline: none;
}}
QListWidget#agentSteps::item, QListWidget#agentFiles::item {{ padding: 6px 10px; border-radius: 8px; }}
QListWidget#agentFiles::item:selected {{ background: rgba(88, 140, 255, 0.24); color: #ffffff; }}
QPlainTextEdit#agentCode {{
    background: #060a16; border: 1px solid rgba(130, 170, 255, 0.18); border-radius: 14px;
    padding: 10px 12px; color: #d6e2f5; selection-background-color: {ACCENT}; selection-color: #04060d;
    font-family: 'Yuki Mono', 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace; font-size: 12.5px;
}}
QLabel#agentWhere {{ color: rgba(185, 196, 216, 0.85); font-size: 12px; }}
"""

_STATUS = {"run": "◌", "ok": "✓", "fail": "✕", "plan": "   ·"}
_STATUS_COLOR = {"run": "#58b6ff", "ok": "#5ee6a8", "fail": "#ff6b85", "plan": "#b9c4d8"}
_KEYWORDS = (r"\b(?:and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|"
             r"global|if|import|in|is|lambda|None|nonlocal|not|or|pass|raise|return|True|False|try|while|with|"
             r"yield|self|const|let|var|function|new|this|null|undefined|export|default)\b")


class CodeHighlighter(QSyntaxHighlighter):
    """Подсветка без лишних библиотек: ключевые слова, строки, числа, комментарии."""

    def __init__(self, document) -> None:
        super().__init__(document)

        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            if bold:
                style.setFontWeight(QFont.Weight.DemiBold)
            style.setFontItalic(italic)
            return style

        self._rules = (
            (re.compile(_KEYWORDS), fmt("#a48dff", bold=True)),
            (re.compile(r"\b(?:def|class|function)\s+(\w+)"), fmt("#58b6ff", bold=True)),
            (re.compile(r"\b\d+(?:\.\d+)?\b"), fmt("#ffb86b")),
        )
        # строки и комментарии — одним проходом слева направо: «#» внутри строки
        # (цвет "#1e1e2e") не должен превращать её остаток в комментарий
        self._literal = re.compile(r"(?P<text>(['\"])(?:\\.|(?!\2).)*\2)|(?P<note>#[^\n]*|//[^\n]*)")
        self._text_style = fmt("#5ee6a8")
        self._note_style = fmt("#6b7a99", italic=True)

    def highlightBlock(self, text: str) -> None:
        for pattern, style in self._rules:
            for match in pattern.finditer(text):
                start, end = match.span(1) if match.lastindex else match.span()
                self.setFormat(start, end - start, style)
        for match in self._literal.finditer(text):
            style = self._text_style if match.group("text") else self._note_style
            self.setFormat(match.start(), match.end() - match.start(), style)


class _Relay(QObject):
    event = Signal(dict)


class AgentPage(QWidget):
    """Задача → ход работы → файлы и код. Запуск и остановка — через `Actions.extras`."""

    def __init__(self, start, stop, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(PAGE_QSS)
        self._start, self._stop = start, stop
        self._root: Path | None = None
        self._files: dict[str, str] = {}
        self._parent = coder_desktop()
        self._streaming = False

        self._relay = _Relay(self)
        self._relay.event.connect(self._on_event, Qt.ConnectionType.QueuedConnection)
        bus.bus.subscribe_callback(lambda event: event.get("type") == "coder" and self._relay.event.emit(event))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(14)
        left.addWidget(self._task_card())
        left.addWidget(self._steps_card(), 1)
        layout.addLayout(left, 2)
        layout.addWidget(self._code_card(), 3)

    # ---------------------------------------------------------------- задача

    def _task_card(self) -> Card:
        card = Card(i18n.t("Задача"), i18n.t(
            "Опиши, что написать. Юки спланирует проект, напишет код, запустит его и сама исправит ошибки. "
            "Голосом: «Юки, напиши игру змейка»."))
        self.task = QTextEdit()
        self.task.setPlaceholderText(i18n.t("Например: калькулятор с историей вычислений и тёмной темой"))
        self.task.setFixedHeight(92)
        self.task.setAccessibleName(i18n.t("Задача для агента"))
        card.add(self.task)

        self.where = QLabel()
        self.where.setObjectName("agentWhere")
        self._show_where()
        change = QPushButton(i18n.t("Изменить"))
        change.setObjectName("menuGhost")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(self._choose_parent)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 2, 0, 0)
        line.addWidget(self.where, 1)
        line.addWidget(change)
        card.add(row)

        self.create = self._action(i18n.t("Создать проект"), self._create, ghost=False)
        self.improve = self._action(i18n.t("Доработать папку…"), self._improve)
        self.stop = self._action(i18n.t("Стоп"), self._stop)
        self.stop.setEnabled(False)
        buttons = QWidget()
        actions = QHBoxLayout(buttons)
        actions.setContentsMargins(0, 6, 0, 0)
        actions.setSpacing(8)
        for button in (self.create, self.improve, self.stop):
            actions.addWidget(button)
        actions.addStretch(1)
        card.add(buttons)
        return card

    def _action(self, text: str, handler, ghost: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("menuGhost" if ghost else "menuAction")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: handler())
        return button

    def _show_where(self) -> None:
        self.where.setText(i18n.t("Куда: {path}").format(path=self._parent))

    def _choose_parent(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, i18n.t("Где создавать проекты"), str(self._parent))
        if folder:
            self._parent = Path(folder)
            self._show_where()

    def _create(self) -> None:
        task = self.task.toPlainText().strip()
        if not task:
            self.task.setFocus()
            return
        self._start(task, None, self._parent)

    def _improve(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, i18n.t("Какой проект доработать"), str(self._parent))
        task = self.task.toPlainText().strip()
        if folder and task:
            self._start(task, Path(folder), None)
        elif folder:
            self.task.setPlaceholderText(i18n.t("Сначала напиши, что изменить в проекте"))
            self.task.setFocus()

    # ---------------------------------------------------------------- ход работы

    def _steps_card(self) -> Card:
        card = Card(i18n.t("Ход работы"), i18n.t("План, код, проверка запуском и исправления — по шагам."))
        self.steps = QListWidget()
        self.steps.setObjectName("agentSteps")
        self.steps.setMinimumHeight(200)
        self.steps.setAccessibleName(i18n.t("Шаги агента"))
        card.add(self.steps)
        return card

    def _step(self, text: str, status: str = "ok") -> None:
        # «◌ Пишу код» сменяется результатом, а не висит рядом с ним
        last = self.steps.item(self.steps.count() - 1) if self.steps.count() else None
        if last is not None and last.data(Qt.ItemDataRole.UserRole) == "run" and status != "run":
            self.steps.takeItem(self.steps.count() - 1)
        item = QListWidgetItem(f"{_STATUS.get(status, '•')}  {text}")
        item.setForeground(QColor(_STATUS_COLOR.get(status, TEXT)))
        item.setData(Qt.ItemDataRole.UserRole, status)
        self.steps.addItem(item)
        self.steps.scrollToBottom()

    # ---------------------------------------------------------------- код

    def _code_card(self) -> Card:
        card = Card(i18n.t("Код"), i18n.t("Файлы проекта. Пока Юки пишет, код появляется здесь вживую."))
        self.files = QListWidget()
        self.files.setObjectName("agentFiles")
        self.files.setFixedHeight(96)
        self.files.setAccessibleName(i18n.t("Файлы проекта"))
        self.files.currentItemChanged.connect(self._show_file)
        card.add(self.files)

        self.code = QPlainTextEdit()
        self.code.setObjectName("agentCode")
        self.code.setReadOnly(True)
        self.code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code.setFont(fonts.font(fonts.MONO, 10))
        self.code.setMinimumHeight(320)
        self.code.setAccessibleName(i18n.t("Код файла"))
        self._highlighter = CodeHighlighter(self.code.document())
        card.add(self.code)

        self.open_folder = self._action(i18n.t("Открыть папку"), lambda: self._root and coderun.open_result(
            self._root, "folder", ""))
        self.open_editor = self._action(i18n.t("Открыть в VS Code"), lambda: self._root and coderun.open_in_editor(
            self._root))
        for button in (self.open_folder, self.open_editor):
            button.setEnabled(False)
        row = QWidget()
        buttons = QHBoxLayout(row)
        buttons.setContentsMargins(0, 6, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self.open_folder)
        buttons.addWidget(self.open_editor)
        buttons.addStretch(1)
        card.add(row)
        return card

    def _show_file(self, item: QListWidgetItem | None) -> None:
        if item is None or self._streaming:
            return
        self.code.setPlainText(self._files.get(item.text(), ""))

    def _add_file(self, path: str, content: str) -> None:
        self._files[path] = content
        matches = self.files.findItems(path, Qt.MatchFlag.MatchExactly)
        item = matches[0] if matches else QListWidgetItem(path)
        if not matches:
            self.files.addItem(item)
        self._streaming = False
        self.files.setCurrentItem(item)
        self.code.setPlainText(content)

    def _stream(self, text: str) -> None:
        if not self._streaming:
            self._streaming = True
            self.code.clear()
        cursor = self.code.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.code.setTextCursor(cursor)
        self.code.ensureCursorVisible()

    # ---------------------------------------------------------------- события агента

    def _on_event(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "start":
            self.steps.clear()
            self.files.clear()
            self._files.clear()
            self.code.clear()
            self._root = None
            if not self.task.toPlainText().strip():
                self.task.setPlainText(str(event.get("text") or ""))
            self._busy(True)
        elif kind == "plan":
            self._root = Path(str(event.get("root")))
            self._step(f"{event.get('title')}: {event.get('text')}", "ok")
            for feature in event.get("features") or []:
                self._step(str(feature), "plan")
            self.open_folder.setEnabled(True)
            self.open_editor.setEnabled(True)
        elif kind == "step":
            self._step(str(event.get("text")), str(event.get("status") or "ok"))
        elif kind == "stream":
            self._stream(str(event.get("text") or ""))
        elif kind == "file":
            self._add_file(str(event.get("path")), str(event.get("content") or ""))
        elif kind == "check":
            title = str(event.get("text"))
            self._step(i18n.t("Проверка «{title}»").format(title=title), "ok" if event.get("ok") else "fail")
            if not event.get("ok") and event.get("output"):
                self._streaming = False
                self.code.setPlainText(str(event.get("output")))
        elif kind == "done":
            self._step(str(event.get("text")), "ok" if event.get("ok") else "fail")
            self._busy(False)

    def _busy(self, busy: bool) -> None:
        self.create.setEnabled(not busy)
        self.improve.setEnabled(not busy)
        self.stop.setEnabled(busy)


def coder_desktop() -> Path:
    from core import coding as coder

    return coder.desktop()
