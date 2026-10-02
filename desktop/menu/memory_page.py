"""Вкладка «Память»: что Юки знает о тебе — посмотреть, добавить, удалить.

Юки запоминает факты сама, из обычного разговора («я работаю дизайнером»,
«у меня кот Барсик»). Доверие к этому держится на прозрачности: здесь видно
каждую запись, и любую можно стереть одним нажатием.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core import i18n, memory

from .controls import Card


class MemoryPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        card = Card(i18n.t("Что Юки знает о тебе"), i18n.t(
            "Юки запоминает факты из разговора сама: где ты учишься, что любишь, как зовут близких. "
            "Голосом: «запомни, что…», «что ты обо мне знаешь», «забудь про…». Всё хранится только "
            "на этом компьютере, в data/memory.json."))
        self.count = QLabel()
        self.count.setObjectName("rowHint")
        card.add(self.count)
        self.list = QWidget()
        self._rows = QVBoxLayout(self.list)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(6)
        card.add(self.list)

        self.input = QLineEdit()
        self.input.setObjectName("menuInput")
        self.input.setPlaceholderText(i18n.t("например: я учусь в 9 классе и люблю рок"))
        self.input.setAccessibleName(i18n.t("Новый факт для памяти"))
        self.input.returnPressed.connect(self._add)
        add = QPushButton(i18n.t("Запомнить"))
        add.setObjectName("menuAction")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(self._add)
        form = QWidget()
        row = QHBoxLayout(form)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.input, 1)
        row.addWidget(add)
        card.add(form)
        layout.addWidget(card)
        layout.addStretch(1)
        self._render()

    def _render(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        facts = list(memory.all_facts())[::-1]
        self.count.setText(i18n.t("Записей: {n}").format(n=len(facts)) if facts else
                           i18n.t("Пока пусто. Расскажи Юки о себе — она запомнит."))
        for fact in facts:
            line = QWidget()
            box = QHBoxLayout(line)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(10)
            text = QLabel(fact.text)
            text.setObjectName("rowLabel")
            text.setWordWrap(True)
            meta = QLabel(f"{fact.tag} · {fact.at}" if fact.at else fact.tag)
            meta.setObjectName("rowHint")
            remove = QPushButton("×")
            remove.setObjectName("menuRemove")
            remove.setFixedSize(30, 30)
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setToolTip(i18n.t("Забыть"))
            remove.setAccessibleName(i18n.t("Забыть: {text}").format(text=fact.text))
            remove.clicked.connect(lambda _=False, value=fact.text: self._forget(value))
            box.addWidget(text, 1)
            box.addWidget(meta)
            box.addWidget(remove)
            self._rows.addWidget(line)

    def _add(self) -> None:
        text = self.input.text().strip()
        if len(text) < 3:
            return
        memory.remember(text, "от тебя")
        self.input.clear()
        self._render()

    def _forget(self, text: str) -> None:
        memory.forget_exact(text)
        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._render()  # Юки могла запомнить новое, пока вкладка была закрыта
