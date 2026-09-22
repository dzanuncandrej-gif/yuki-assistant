"""Раздел «Сообщения»: выбрать мессенджер, найти человека, продиктовать, отправить.

Порядок шагов на экране повторяет порядок проверок внутри. Кнопка «Отправить»
недоступна, пока адресат не найден и не подтверждён — не из вежливости, а потому
что отправленное чужому человеку сообщение не отзывается назад.

Долгие шаги (запуск мессенджера, поиск) идут в отдельном потоке: интерфейс не
должен замирать на те несколько секунд, пока открывается Telegram.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import i18n, outbox

from .controls import Card, Row


class _Worker(QObject):
    """Один долгий шаг в фоне: поиск или отправка."""

    done = Signal(object, str)  # результат, текст ошибки

    def __init__(self, job: Callable[[], object]) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:
        try:
            self.done.emit(self._job(), "")
        except Exception as err:
            self.done.emit(None, str(err))


class MessagesPage(QWidget):
    """Отправка сообщения через Telegram, Discord или Steam."""

    speak = Signal(str)          # попросить Юки сказать вслух
    dictate = Signal()           # попросить надиктовать текст голосом

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._draft: outbox.Draft | None = None
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._done: Callable[[object, str], None] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        layout.addWidget(self._who_card())
        layout.addWidget(self._text_card())
        layout.addStretch(1)
        self._refresh()

    # ---------------------------------------------------------------- сборка

    def _who_card(self) -> Card:
        card = Card(i18n.t("Кому"), i18n.t("Мессенджер и человек. Юки откроет переписку и покажет, кого нашла."))

        self.service = QComboBox()
        self.service.setObjectName("menuSelect")
        for item in outbox.services():
            self.service.addItem(item.title, item.key)
        self.service.setCursor(Qt.CursorShape.PointingHandCursor)
        card.add(Row(i18n.t("Мессенджер"), self.service, i18n.t("Куда отправлять.")))

        self.contact = QLineEdit()
        self.contact.setObjectName("menuInput")
        self.contact.setMinimumWidth(240)
        self.contact.setPlaceholderText(i18n.t("например: Максиму"))
        self.contact.returnPressed.connect(self._find)
        card.add(Row(i18n.t("Контакт"), self.contact, i18n.t("Имя так, как вы его называете.")))

        self.find_button = QPushButton(i18n.t("Найти контакт"))
        self.find_button.setObjectName("menuAction")
        self.find_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.find_button.clicked.connect(self._find)

        self.confirm_button = QPushButton(i18n.t("Это он"))
        self.confirm_button.setObjectName("menuGhost")
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.clicked.connect(self._confirm)

        self.cancel_button = QPushButton(i18n.t("Отмена"))
        self.cancel_button.setObjectName("menuGhost")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._cancel)

        buttons = QWidget()
        line = QHBoxLayout(buttons)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(self.find_button)
        line.addWidget(self.confirm_button)
        line.addWidget(self.cancel_button)
        line.addStretch(1)
        card.add(buttons)

        self.status = QLabel(i18n.t("Выберите мессенджер и введите имя."))
        self.status.setObjectName("rowHint")
        self.status.setWordWrap(True)
        card.add(self.status)
        return card

    def _text_card(self) -> Card:
        card = Card(i18n.t("Что написать"), i18n.t("Наберите текст или продиктуйте голосом."))

        self.message = QTextEdit()
        self.message.setPlaceholderText(i18n.t("Текст сообщения…"))
        self.message.setFixedHeight(96)
        self.message.textChanged.connect(self._refresh)
        card.add(self.message)

        self.dictate_button = QPushButton(i18n.t("Продиктовать"))
        self.dictate_button.setObjectName("menuGhost")
        self.dictate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dictate_button.clicked.connect(self.dictate.emit)

        self.send_button = QPushButton(i18n.t("Отправить"))
        self.send_button.setObjectName("menuAction")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self._send)

        buttons = QWidget()
        line = QHBoxLayout(buttons)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(self.dictate_button)
        line.addWidget(self.send_button)
        line.addStretch(1)
        card.add(buttons)
        return card

    # ---------------------------------------------------------------- состояние

    def _refresh(self) -> None:
        """Кнопки включаются ровно тогда, когда следующий шаг действительно возможен."""
        busy = self._thread is not None
        draft = self._draft
        ready = draft is not None and bool(draft.found)
        sure = ready and (draft.certain or draft.confirmed)

        self.find_button.setEnabled(not busy and bool(self.contact.text().strip()))
        self.confirm_button.setEnabled(not busy and ready and not draft.certain
                                       and not draft.confirmed)
        self.cancel_button.setEnabled(not busy and draft is not None)
        self.send_button.setEnabled(
            not busy and sure and bool(self.message.toPlainText().strip())
        )

    def set_dictated(self, text: str) -> None:
        """Текст, надиктованный голосом, попадает в поле сообщения."""
        if text.strip():
            self.message.setPlainText(text.strip())
            self._refresh()

    # ---------------------------------------------------------------- шаги

    def _run(self, job: Callable[[], object], done: Callable[[object, str], None]) -> None:
        """Запускает долгий шаг в отдельном потоке, а ответ принимает в своём.

        Тонкое место, из-за которого окно раньше зависало и закрывалось:
        `worker.done` испускается в рабочем потоке, а обычная функция получателем
        быть не может — у неё нет своего потока, и Qt вызывает её прямо там, где
        сигнал возник. В итоге поток ждал `thread.wait()` сам себя, а надписи
        обновлялись не из главного потока — это уже неопределённое поведение Qt,
        которое Windows показывает как «не отвечает».

        Метод объекта страницы такой двусмысленности не создаёт: страница живёт в
        главном потоке, Qt сам ставит вызов в его очередь.
        """
        thread = QThread(self)
        worker = _Worker(job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_worker_done)
        thread.finished.connect(thread.deleteLater)

        self._thread, self._worker, self._done = thread, worker, done
        self._refresh()
        thread.start()

    def _on_worker_done(self, result: object, error: str) -> None:
        """Итог фонового шага — уже в главном потоке."""
        thread, done = self._thread, self._done
        self._thread, self._worker, self._done = None, None, None
        if thread is not None:
            thread.quit()   # ждать завершения здесь нельзя: поток закончится сам
        if done is not None:
            done(result, error)
        self._refresh()

    def _find(self) -> None:
        name = self.contact.text().strip()
        if not name or self._thread is not None:
            return
        service = str(self.service.currentData())
        self.status.setText(f"Открываю {self.service.currentText()} и ищу «{name}»…")
        self._draft = None

        def job() -> object:
            draft = outbox.prepare(service, name)
            if draft.found:
                outbox.open_found(draft)
            return draft

        def done(result: object, error: str) -> None:
            if error:
                self.status.setText(f"Не вышло: {error}")
                return
            draft = result  # type: ignore[assignment]
            self._draft = draft
            if not draft.found:
                others = ", ".join(draft.candidates) or "ничего похожего"
                self.status.setText(f"Контакт «{name}» не найден. В списке: {others}")
                return
            if draft.certain:
                self.status.setText(f"Нашла «{draft.found}» — переписка открыта. Можно писать.")
                self.speak.emit(f"Нашла {draft.found}. Что мне ему написать?")
            else:
                others = ", ".join(draft.candidates)
                self.status.setText(
                    f"Нашла «{draft.found}», но это не точное совпадение с «{name}». "
                    f"Варианты: {others}. Нажмите «Это он», если адресат верный."
                )
                self.speak.emit(f"Нашла {draft.found}. Это тот человек?")

        self._run(job, done)

    def _confirm(self) -> None:
        if self._draft is not None:
            self._draft.confirmed = True
            self.status.setText(f"Адресат подтверждён: {self._draft.found}. Можно отправлять.")
            self._refresh()

    def _cancel(self) -> None:
        outbox.cancel()
        self._draft = None
        self.status.setText("Отменено. Ничего не отправлено.")
        self._refresh()

    def _send(self) -> None:
        draft, text = self._draft, self.message.toPlainText().strip()
        if draft is None or not text or self._thread is not None:
            return
        self.status.setText(f"Отправляю «{draft.found}»…")

        def job() -> object:
            return outbox.deliver(draft, text)

        def done(result: object, error: str) -> None:
            if error:
                self.status.setText(f"Не отправлено: {error}")
                return
            self.status.setText(f"Отправлено: {result}")
            self.speak.emit(f"Отправила {result}.")
            self.message.clear()
            self._draft = None

        self._run(job, done)
