"""Меню управления: прямоугольное окно с боковой навигацией и плавными переходами.

Оформление — тёмный космос: почти чёрный фон, звёздная пыль, стеклянные карточки,
мягкое свечение выбранного раздела. Никакой системной рамки: окно рисует себя само.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QKeySequence, QPainterPath, QRegion, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import i18n

from ..theme import MENU_QSS
from .controls import Starfield
from .messages import MessagesPage
from .nav import BrandMark, CallButton, IconButton, NavButton, NavHighlight, SectionTile, StatusCard
from .pages import Actions, account_page, ai_page, character_page, language_page, voice_page
from .scenarios import ScenariosPage
from .settings import SettingsStore

WINDOW_SIZE = QSize(1280, 820)
CORNER_RADIUS = 18

# Разделы сгруппированы по смыслу, а не свалены в один столбец. Их стало вдвое
# больше, и плоский список из десятка пунктов читается уже плохо: глазу не за что
# зацепиться. Группа с заголовком отвечает на вопрос «где это искать» раньше, чем
# человек прочитает все названия.
_RAW_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str, str], ...]], ...] = (
    ("ДЕЙСТВИЯ", (
        ("messages", "✉  СООБЩЕНИЯ", "Сообщения",
         "Telegram, Discord и Steam: найти человека и отправить сообщение"),
        ("scenarios", "⚡  СЦЕНАРИИ", "Сценарии",
         "Несколько действий под одним именем — одной фразой или одним нажатием"),
        ("agent", "⌘  АГЕНТ", "Агент",
         "Юки пишет код: планирует, запускает, сама исправляет ошибки"),
        ("playlist", "♫  ПЛЕЙЛИСТ", "Плейлист",
         "Твоя музыка: «Юки, включи мою музыку» играет именно её"),
    )),
    ("ЮКИ", (
        ("voice", "◧  ГОЛОС", "Голос и слух", "Тембр ассистента, микрофон, распознавание речи"),
        ("character", "❋  ПЕРСОНАЖ", "Персонаж", "Живой компаньон на рабочем столе"),
        ("memory", "◉  ПАМЯТЬ", "Память", "Что Юки знает о тебе — посмотреть, добавить, удалить"),
        ("ai", "◈  ИНТЕЛЛЕКТ", "Интеллект", "Модель, поведение, зрение и жесты"),
    )),
    ("СИСТЕМА", (
        ("language", "◨  ЯЗЫК", "Язык", "Язык интерфейса и язык, на котором вас слушают"),
        ("account", "◍  АККАУНТ", "Аккаунт", "Оператор, город, область поиска, состояние системы"),
    )),
)


def _translated_groups() -> tuple[tuple[str, tuple[tuple[str, str, str, str], ...]], ...]:
    return tuple(
        (i18n.t(group_title), tuple(
            (key, i18n.t(caption), i18n.t(title), i18n.t(subtitle))
            for key, caption, title, subtitle in items
        ))
        for group_title, items in _RAW_GROUPS
    )


GROUPS: tuple[tuple[str, tuple[tuple[str, str, str, str], ...]], ...] = _translated_groups()

SECTIONS: tuple[tuple[str, str, str, str], ...] = tuple(
    item for _, items in GROUPS for item in items
)


class Sidebar(QWidget):
    """Боковая панель, которая держит светящуюся плашку под выбранным пунктом."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # плашка создаётся первой — значит, рисуется под кнопками
        self.highlight = NavHighlight(self)
        self._group: QButtonGroup | None = None

    def bind(self, group: QButtonGroup) -> None:
        self._group = group
        group.buttonToggled.connect(lambda button, checked: checked and self.sync(True))

    def sync(self, animate: bool = False) -> None:
        button = self._group.checkedButton() if self._group is not None else None
        if button is None or not button.isVisible():
            self.highlight.hide()
            return
        self.highlight.show()
        self.highlight.move_to(button.geometry(), animate)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, lambda: self.sync(False))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self.sync(False))


class SmoothScroll(QScrollArea):
    """Прокрутка колесом с инерцией: страница доезжает, а не прыгает рывками.

    Каждый щелчок колеса сдвигает цель, а полоса плавно догоняет её. Быстрая
    серия щелчков складывается в один длинный мягкий проезд.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._target = 0
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def wheelEvent(self, event) -> None:
        bar = self.verticalScrollBar()
        delta = event.angleDelta().y()
        if not delta or bar.maximum() == 0:
            super().wheelEvent(event)
            return
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._target = bar.value()
        self._target = max(bar.minimum(), min(bar.maximum(), self._target - int(delta * 1.1)))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(self._target)
        self._anim.start()
        event.accept()


def _scrollable(page: QWidget) -> QScrollArea:
    """Каждый раздел прокручивается сам по себе.

    Одна общая прокрутка на все разделы не годится: QStackedWidget запрашивает
    ширину по самой широкой странице, и узкие разделы уезжают за край окна.
    """
    scroll = SmoothScroll()
    scroll.setObjectName("menuScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(page)
    return scroll


class ControlMenu(QWidget):
    """Окно настроек. Значения применяются сразу, без кнопки «сохранить»."""

    closed = Signal()

    def __init__(self, store: SettingsStore, actions: Actions | None = None,
                 parent: QWidget | None = None,
                 extra: Sequence[tuple[str, str, str, str, QWidget]] = (),
                 on_call: Callable[[], None] | None = None,
                 pages: dict[str, QWidget] | None = None) -> None:
        super().__init__(parent)
        self._on_call = on_call
        self._store = store
        self._actions = actions or Actions()
        # готовые разделы можно добавить снаружи: так главное окно вставляет
        # диалог, не дублируя ни навигацию, ни оформление
        self._extra = {item[0]: item[4] for item in extra}
        # готовые страницы на месте обычных разделов: «Агент» и «Плейлист» на веб-движке
        self._extra.update(pages or {})
        self._sections = tuple(item[:4] for item in extra) + SECTIONS

        self.setWindowTitle(i18n.t("Юки — управление"))
        self.setObjectName("menuRoot")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(MENU_QSS)
        self.resize(WINDOW_SIZE)
        self.setMinimumSize(QSize(880, 560))

        self.background = Starfield(self)
        self.pages = QStackedWidget()
        self.title = QLabel(self._sections[0][2])
        self.title.setObjectName("menuTitle")
        self.subtitle = QLabel(self._sections[0][3])
        self.subtitle.setObjectName("menuSubtitle")

        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_content(), 1)

        self._build_pages()
        self._install_shortcuts()
        self._fade_in()

    # ---------------------------------------------------------------- сборка

    def _build_sidebar(self) -> QWidget:
        sidebar = Sidebar()
        sidebar.setObjectName("menuSidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(284)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 20)
        layout.setSpacing(2)
        layout.addWidget(BrandMark())
        layout.addSpacing(14)
        self.status_card = StatusCard()
        layout.addWidget(self.status_card)
        layout.addSpacing(14)

        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        order = {key: index for index, (key, _, _, _) in enumerate(self._sections)}
        titles = {key: title for key, _, title, _ in self._sections}
        extra_keys = [key for key in order if key not in
                      {item[0] for _, items in GROUPS for item in items}]

        def add_tab(key: str) -> None:
            button = NavButton(key, titles[key])
            button.setChecked(order[key] == 0)
            self._tabs.addButton(button, order[key])
            layout.addWidget(button)

        def add_caption(text: str) -> None:
            caption = QLabel(text)
            caption.setObjectName("menuGroup")
            layout.addSpacing(8)
            layout.addWidget(caption)

        if extra_keys:
            add_caption(i18n.t("ДИАЛОГ"))
            for key in extra_keys:
                add_tab(key)
        for title, items in GROUPS:
            add_caption(title)
            for key, _, _, _ in items:
                if key in order:
                    add_tab(key)
        self._tabs.idClicked.connect(self.show_section)
        sidebar.bind(self._tabs)

        layout.addStretch(1)
        self.call_button = CallButton(i18n.t("Видеосвязь"))
        self.call_button.setVisible(self._on_call is not None)
        if self._on_call is not None:
            self.call_button.clicked.connect(self._on_call)
        layout.addWidget(self.call_button)
        layout.addSpacing(10)
        hint = QLabel(i18n.t("CTRL+ALT+J — окно  ·  ESC — скрыть"))
        hint.setObjectName("menuHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("menuContent")

        self.tile = SectionTile()
        self.tile.set_key(self._sections[0][0])

        minimize = IconButton("minimize")
        minimize.setToolTip(i18n.t("Свернуть"))
        minimize.clicked.connect(self.showMinimized)
        close = IconButton("close", danger=True)
        close.setToolTip(i18n.t("ESC — закрыть\nCTRL+ALT+J — окно Юки").splitlines()[0])
        close.clicked.connect(self.close)

        heading = QVBoxLayout()
        heading.setContentsMargins(0, 2, 0, 0)
        heading.setSpacing(3)
        heading.addWidget(self.title)
        heading.addWidget(self.subtitle)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(16)
        header.addWidget(self.tile, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addLayout(heading, 1)
        header.addWidget(minimize, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        rule = QFrame()
        rule.setObjectName("menuRule")
        rule.setFixedHeight(1)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 24, 26, 22)
        layout.setSpacing(18)
        layout.addLayout(header)
        layout.addWidget(rule)
        layout.addWidget(self.pages, 1)
        return content

    def _build_pages(self) -> None:
        builders: dict[str, Callable[[SettingsStore, Actions], QWidget]] = {
            "voice": voice_page,
            "language": language_page,
            "ai": ai_page,
            "character": character_page,
            "account": account_page,
            "messages": lambda store, actions: self._messages_page(actions),
            "scenarios": lambda store, actions: self._scenarios_page(actions),
            "playlist": lambda store, actions: self._playlist_page(),
            "agent": lambda store, actions: self._agent_page(actions),
            "memory": lambda store, actions: self._memory_page(),
        }
        for key, _, _, _ in self._sections:
            ready = self._extra.get(key)
            self.pages.addWidget(ready if ready is not None
                                 else _scrollable(builders[key](self._store, self._actions)))

    def _messages_page(self, actions: Actions) -> QWidget:
        """Страница сообщений. Её сигналы уходят в приложение через `Actions.extras`."""
        page = MessagesPage()
        speak = actions.extras.get("say")
        if speak is not None:
            page.speak.connect(speak)
        dictate = actions.extras.get("dictate_message")
        if dictate is not None:
            page.dictate.connect(lambda: dictate(page.set_dictated))
        self.messages = page
        return page

    def _memory_page(self) -> QWidget:
        from .memory_page import MemoryPage

        self.memory = MemoryPage()
        return self.memory

    def _agent_page(self, actions: Actions) -> QWidget:
        from .agent_page import AgentPage

        start = actions.extras.get("code_start") or (lambda *_: None)
        stop = actions.extras.get("code_stop") or (lambda: None)
        self.agent = AgentPage(start, stop)
        return self.agent

    def _playlist_page(self) -> QWidget:
        from .playlist_page import PlaylistPage

        self.playlist = PlaylistPage()
        return self.playlist

    def _scenarios_page(self, actions: Actions) -> QWidget:
        page = ScenariosPage()
        speak = actions.extras.get("say")
        if speak is not None:
            page.speak.connect(speak)
        self.scenarios = page
        return page

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)

    # ---------------------------------------------------------------- поведение

    def show_section(self, index: int) -> None:
        if index < 0 or index >= self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        key, _, title, subtitle = self._sections[index]
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.tile.set_key(key)
        self._fade_header()
        holder = self.pages.currentWidget()
        page = holder.widget() if isinstance(holder, QScrollArea) else holder
        self._slide_page(holder, page)
        button = self._tabs.button(index)
        if button is not None:
            button.setChecked(True)

    def _fade_header(self) -> None:
        """Заголовок и плитка раздела проявляются вместе со страницей."""
        for widget in (self.title, self.subtitle, self.tile):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", widget)
            fade.setDuration(380)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade.finished.connect(lambda target=widget: target.setGraphicsEffect(None))
            fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def open_section(self, key: str) -> None:
        for index, section in enumerate(self._sections):
            if section[0] == key:
                self.show_section(index)
                return

    def _slide_page(self, holder: QWidget, page: QWidget) -> None:
        """Страница проявляется и подъезжает снизу.

        Прозрачность вешается на область прокрутки, а не на её содержимое: эффект
        рисует источник в отдельный слой и на прокручиваемом виджете сдвигает
        картинку. Движение делаем верхним отступом layout — компоновка не ломается.
        """
        # эффект прозрачности рисует виджет в отдельный слой и сбивает координаты
        # вложенной прокрутки. Разделам-обёрткам это не мешает, а готовым
        # страницам с собственным списком (диалог) — ломает всю компоновку
        if isinstance(holder, QScrollArea):
            effect = QGraphicsOpacityEffect(holder)
            holder.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", holder)
            fade.setDuration(360)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            # Эффект обязательно снять по окончании. Пока он висит, Qt рисует
            # виджет через закадровый слой, и область прокрутки съезжает вправо
            # и вниз на каждый поворот колеса. Раньше эффект оставался навсегда.
            fade.finished.connect(lambda: holder.setGraphicsEffect(None))
            fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        layout = page.layout()
        if layout is None:
            return
        left, _, right, bottom = layout.getContentsMargins()
        slide = QVariantAnimation(page)
        slide.setDuration(460)
        slide.setStartValue(34)
        slide.setEndValue(0)
        slide.setEasingCurve(QEasingCurve.Type.OutQuint)
        slide.valueChanged.connect(
            lambda value: layout.setContentsMargins(left, int(value), right, bottom)
        )
        slide.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _fade_in(self) -> None:
        """Готовит появление окна.

        Эффект вешается только на время анимации: постоянный слой на корневом
        окне заставлял всё содержимое рисоваться через закадровый буфер — лишняя
        работа на каждый кадр и та же беда с прокруткой, что была у разделов.
        """
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self._appear = QPropertyAnimation(self._opacity, b"opacity", self)
        self._appear.setDuration(380)
        self._appear.setStartValue(0.0)
        self._appear.setEndValue(1.0)
        self._appear.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._appear.finished.connect(lambda: self.setGraphicsEffect(None))

    def show_centered(self, anchor: QWidget | None = None) -> None:
        """Открывает меню по центру экрана и мягко проявляет его."""
        from PySide6.QtWidgets import QApplication

        screen = (anchor.screen() if anchor is not None else None) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        self._appear.stop()
        self.setGraphicsEffect(self._opacity)
        self._appear.start()

    def apply_config(self, cfg: Mapping[str, Any]) -> None:
        """Полное обновление значений — например, после смены голоса командой."""
        for section, values in cfg.items():
            if isinstance(values, Mapping):
                for key, value in values.items():
                    self._store.set(section, key, value)

    # ---------------------------------------------------------------- окно

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 90:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.background.setGeometry(self.rect())
        self.background.lower()
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), CORNER_RADIUS, CORNER_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def closeEvent(self, event) -> None:
        self._store.flush()
        self.closed.emit()
        super().closeEvent(event)
