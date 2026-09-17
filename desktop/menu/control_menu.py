"""Меню управления: прямоугольное окно с боковой навигацией и плавными переходами.

Оформление — тёмный космос: почти чёрный фон, звёздная пыль, стеклянные карточки,
мягкое свечение выбранного раздела. Никакой системной рамки: окно рисует себя само.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QKeySequence, QPainterPath, QRegion, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import i18n

from ..theme import MENU_QSS
from .controls import Starfield
from .messages import MessagesPage
from .scenarios import ScenariosPage
from .pages import Actions, ai_page, account_page, character_page, language_page, voice_page
from .settings import SettingsStore

WINDOW_SIZE = QSize(1080, 700)
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
    )),
    ("ЮКИ", (
        ("voice", "◧  ГОЛОС", "Голос и слух", "Тембр ассистента, микрофон, распознавание речи"),
        ("character", "❋  ПЕРСОНАЖ", "Персонаж", "Живой компаньон на рабочем столе"),
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


def _scrollable(page: QWidget) -> QScrollArea:
    """Каждый раздел прокручивается сам по себе.

    Одна общая прокрутка на все разделы не годится: QStackedWidget запрашивает
    ширину по самой широкой странице, и узкие разделы уезжают за край окна.
    """
    scroll = QScrollArea()
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
                 extra: Sequence[tuple[str, str, str, str, QWidget]] = ()) -> None:
        super().__init__(parent)
        self._store = store
        self._actions = actions or Actions()
        # готовые разделы можно добавить снаружи: так главное окно вставляет
        # диалог, не дублируя ни навигацию, ни оформление
        self._extra = {item[0]: item[4] for item in extra}
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
        self.title = QLabel(self._sections[0][2].upper())
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
        sidebar = QWidget()
        sidebar.setObjectName("menuSidebar")
        sidebar.setFixedWidth(260)

        brand = QLabel("Y U K I")
        brand.setObjectName("menuBrand")
        sub = QLabel("CONTROL DECK")
        sub.setObjectName("menuBrandSub")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(22, 26, 18, 20)
        layout.setSpacing(6)
        layout.addWidget(brand)
        layout.addWidget(sub)
        layout.addSpacing(26)

        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        order = {key: index for index, (key, _, _, _) in enumerate(self._sections)}
        extra_keys = [key for key in order if key not in
                      {item[0] for _, items in GROUPS for item in items}]

        def add_tab(key: str, caption: str) -> None:
            button = QPushButton(caption)
            button.setObjectName("menuTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(order[key] == 0)
            self._tabs.addButton(button, order[key])
            layout.addWidget(button)

        def add_caption(text: str) -> None:
            caption = QLabel(text)
            caption.setObjectName("menuGroup")
            layout.addSpacing(10)
            layout.addWidget(caption)

        if extra_keys:
            add_caption(i18n.t("ДИАЛОГ"))
            for key in extra_keys:
                add_tab(key, dict((item[0], item[1]) for item in self._sections)[key])
        for title, items in GROUPS:
            add_caption(title)
            for key, caption, _, _ in items:
                if key in order:
                    add_tab(key, caption)
        self._tabs.idClicked.connect(self.show_section)

        layout.addStretch(1)

        hint = QLabel(i18n.t("ESC — закрыть\nCTRL+ALT+J — окно Юки"))
        hint.setObjectName("menuSubtitle")
        layout.addWidget(hint)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()

        close = QPushButton("✕")
        close.setObjectName("menuGhost")
        close.setFixedSize(34, 30)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.close)

        badge = QLabel("LIVE")
        badge.setObjectName("menuBadge")

        heading = QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(4)
        heading.addWidget(self.title)
        heading.addWidget(self.subtitle)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        header.addLayout(heading, 1)
        header.addWidget(badge)
        header.addWidget(close)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 26, 24, 24)
        layout.setSpacing(18)
        layout.addLayout(header)
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
        _, _, title, subtitle = self._sections[index]
        self.title.setText(title.upper())
        self.subtitle.setText(subtitle)
        holder = self.pages.currentWidget()
        page = holder.widget() if isinstance(holder, QScrollArea) else holder
        self._slide_page(holder, page)
        button = self._tabs.button(index)
        if button is not None:
            button.setChecked(True)

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
            fade.setDuration(240)
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
        slide.setDuration(280)
        slide.setStartValue(28)
        slide.setEndValue(0)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
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
        self._appear.setDuration(260)
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

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802 — Qt-нейминг
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 90:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self.background.setGeometry(self.rect())
        self.background.lower()
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), CORNER_RADIUS, CORNER_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self._store.flush()
        self.closed.emit()
        super().closeEvent(event)
