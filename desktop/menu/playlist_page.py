"""Вкладка «Плейлист»: свои песни и проигрыватель Юки.

Песни добавляются кнопками или перетаскиванием файлов и папок прямо на
страницу. Двойной щелчок — играть с этой песни. Голосом: «Юки, включи мою
музыку», «перемешай», «следующая», «что играет».
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core import i18n, playlist

from .. import player as player_mod
from ..theme import ACCENT, TEXT, VIOLET
from .controls import Card

_AUDIO_FILTER = "Музыка (" + " ".join(f"*{ext}" for ext in playlist.AUDIO) + ")"

PAGE_QSS = f"""
QLabel#trackTitle {{ color: #ffffff; font-size: 20px; font-weight: 700; }}
QLabel#trackArtist {{ color: rgba(185, 196, 216, 0.9); font-size: 13px; }}
QLabel#trackTime {{ color: rgba(185, 196, 216, 0.75); font-size: 11.5px; font-family: 'JetBrains Mono', Consolas; }}
QPushButton#playerButton {{
    background: rgba(14, 22, 44, 0.70); border: 1px solid rgba(130, 170, 255, 0.24);
    border-radius: 22px; color: {TEXT}; font-size: 16px; min-width: 44px; min-height: 44px;
}}
QPushButton#playerButton:hover {{ border-color: rgba(88, 182, 255, 0.7); color: #ffffff; }}
QPushButton#playerButton:checked {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#playerMain {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT}, stop:1 {VIOLET});
    border: none; border-radius: 28px; color: #041022; font-size: 20px; font-weight: 800;
    min-width: 56px; min-height: 56px;
}}
QPushButton#playerMain:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #98d4ff, stop:1 #b8a6ff); }}
QListWidget#playlistList {{
    background: rgba(8, 13, 28, 0.55); border: 1px solid rgba(130, 170, 255, 0.14);
    border-radius: 14px; padding: 6px; color: {TEXT}; font-size: 13px; outline: none;
}}
QListWidget#playlistList::item {{ padding: 9px 12px; border-radius: 10px; margin: 1px 0; }}
QListWidget#playlistList::item:hover {{ background: rgba(88, 140, 255, 0.10); }}
QListWidget#playlistList::item:selected {{ background: rgba(88, 140, 255, 0.24); color: #ffffff; }}
"""


# Иконки 24×24 тем же штрихом, что и в навигации: эмодзи Windows рисует цветными.
_GLYPHS = {
    "shuffle": '<path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>',
    "previous": '<path d="M19 20L9 12l10-8z" fill="currentColor"/><path d="M5 19V5"/>',
    "next": '<path d="M5 4l10 8-10 8z" fill="currentColor"/><path d="M19 5v14"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
    "play": '<path d="M7 4.5v15l12.5-7.5z" fill="currentColor"/>',
    "pause": '<rect x="6.5" y="5" width="4" height="14" rx="1" fill="currentColor"/>'
             '<rect x="13.5" y="5" width="4" height="14" rx="1" fill="currentColor"/>',
    "volume": '<path d="M11 5L6 9H2v6h4l5 4z" fill="currentColor"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
}


def _icon(key: str, color: str, size: int = 22) -> QIcon:
    from PySide6.QtSvg import QSvgRenderer

    body = _GLYPHS[key].replace("currentColor", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


def _clock(ms: int) -> str:
    seconds = max(0, int(ms // 1000))
    return f"{seconds // 60}:{seconds % 60:02d}"


class _Relay(QObject):
    """Плейлист меняют и из голосового потока — перерисовка уходит в главный."""

    changed = Signal()


class PlaylistPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet(PAGE_QSS)
        self._player = player_mod.instance()
        self._seeking = False
        self._relay = _Relay(self)
        self._relay.changed.connect(self._render_list, Qt.ConnectionType.QueuedConnection)
        playlist.on_change(self._relay.changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        layout.addWidget(self._now_card())
        layout.addWidget(self._list_card(), 1)

        self._player.changed.connect(self._render_now)
        self._player.progress.connect(self._on_progress)
        self._render_list()
        self._render_now()

    # ---------------------------------------------------------------- сейчас играет

    def _now_card(self) -> Card:
        card = Card(i18n.t("Сейчас играет"), i18n.t(
            "Скажи «Юки, включи мою музыку» — заиграет этот плейлист. «Перемешай», «следующая», «пауза», "
            "«что играет» тоже работают. Пока Юки говорит, музыка становится тише."))
        self.title = QLabel(i18n.t("Тишина"))
        self.title.setObjectName("trackTitle")
        self.title.setWordWrap(True)
        self.artist = QLabel(i18n.t("Выбери песню двойным щелчком или скажи «включи мою музыку»"))
        self.artist.setObjectName("trackArtist")
        card.add(self.title)
        card.add(self.artist)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setObjectName("menuSlider")
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_done)
        self.elapsed = QLabel("0:00")
        self.elapsed.setObjectName("trackTime")
        self.total = QLabel("0:00")
        self.total.setObjectName("trackTime")
        timeline = QWidget()
        row = QHBoxLayout(timeline)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(10)
        row.addWidget(self.elapsed)
        row.addWidget(self.seek, 1)
        row.addWidget(self.total)
        card.add(timeline)

        self.shuffle = self._button("shuffle", i18n.t("Вперемешку"), lambda: self._player.set_shuffle(
            self.shuffle.isChecked()), checkable=True)
        previous = self._button("previous", i18n.t("Предыдущая"), lambda: self._player.step(-1))
        self.main = QPushButton()
        self.main.setIcon(_icon("play", "#041022", 24))
        self.main.setIconSize(QSize(24, 24))
        self.main.setObjectName("playerMain")
        self.main.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main.setToolTip(i18n.t("Играть / пауза"))
        self.main.clicked.connect(self._toggle)
        following = self._button("next", i18n.t("Следующая"), lambda: self._player.step(1))
        stop = self._button("stop", i18n.t("Стоп"), self._player.stop)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setObjectName("menuSlider")
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self._player.volume * 100))
        self.volume.setFixedWidth(140)
        self.volume.setToolTip(i18n.t("Громкость музыки"))
        self.volume.valueChanged.connect(lambda value: self._player.set_volume(value / 100))

        controls = QWidget()
        buttons = QHBoxLayout(controls)
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.setSpacing(10)
        for widget in (self.shuffle, previous, self.main, following, stop):
            buttons.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons.addStretch(1)
        speaker = QLabel()
        speaker.setPixmap(_icon("volume", "#b9c4d8", 18).pixmap(18, 18))
        buttons.addWidget(speaker)
        buttons.addWidget(self.volume)
        card.add(controls)
        return card

    def _button(self, glyph: str, tip: str, handler, checkable: bool = False) -> QPushButton:
        button = QPushButton()
        button.setIcon(_icon(glyph, "#dfe8f7", 18))
        button.setIconSize(QSize(18, 18))
        button.setObjectName("playerButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setCheckable(checkable)
        button.clicked.connect(lambda: handler())
        return button

    def _toggle(self) -> None:
        if self._player.current() is None:
            row = max(0, self.list.currentRow())
            if self.list.count():
                self._player.play(row, shuffle=self.shuffle.isChecked())
            return
        self._player.toggle()

    def _render_now(self) -> None:
        track = self._player.current()
        self.main.setIcon(_icon("pause" if self._player.playing() else "play", "#041022", 24))
        self.shuffle.setChecked(self._player.shuffle)
        if track is None:
            self.title.setText(i18n.t("Тишина"))
            self.artist.setText(i18n.t("Выбери песню двойным щелчком или скажи «включи мою музыку»"))
            self.seek.setRange(0, 0)
            self.elapsed.setText("0:00")
            self.total.setText("0:00")
        else:
            self.title.setText(track.title)
            self.artist.setText(track.artist or Path(track.path).parent.name)
        self._mark_current()

    def _on_progress(self, position: int, duration: int) -> None:
        if self._seeking:
            return
        self.seek.setRange(0, max(0, duration))
        self.seek.setValue(position)
        self.elapsed.setText(_clock(position))
        self.total.setText(_clock(duration))

    def _seek_done(self) -> None:
        self._seeking = False
        self._player.seek(self.seek.value())

    # ---------------------------------------------------------------- список песен

    def _list_card(self) -> Card:
        card = Card(i18n.t("Мои песни"), i18n.t(
            "Добавь аудиофайлы или целую папку — или просто перетащи их сюда. "
            "Delete убирает песню из плейлиста (сам файл остаётся на месте)."))
        self.list = QListWidget()
        self.list.setObjectName("playlistList")
        self.list.setMinimumHeight(260)
        self.list.setAccessibleName(i18n.t("Песни плейлиста"))
        self.list.itemActivated.connect(lambda item: self._player.play(self.list.row(item),
                                                                      shuffle=self.shuffle.isChecked()))
        self.list.installEventFilter(self)
        card.add(self.list)

        self.count = QLabel("")
        self.count.setObjectName("rowHint")
        add_files = QPushButton(i18n.t("Добавить песни"))
        add_files.setObjectName("menuAction")
        add_files.setCursor(Qt.CursorShape.PointingHandCursor)
        add_files.clicked.connect(self._add_files)
        add_folder = QPushButton(i18n.t("Добавить папку"))
        add_folder.setObjectName("menuGhost")
        add_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        add_folder.clicked.connect(self._add_folder)
        remove = QPushButton(i18n.t("Убрать выбранную"))
        remove.setObjectName("menuGhost")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(self._remove_selected)
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(8)
        row.addWidget(add_files)
        row.addWidget(add_folder)
        row.addWidget(remove)
        row.addStretch(1)
        row.addWidget(self.count)
        card.add(row_widget)
        return card

    def _render_list(self) -> None:
        selected = self.list.currentRow()
        self.list.clear()
        items = playlist.tracks()
        for number, track in enumerate(items, start=1):
            text = f"{number:>2}.  {track.title}" + (f"   ·   {track.artist}" if track.artist else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, track.path)
            item.setToolTip(track.path)
            if not track.exists:
                item.setForeground(Qt.GlobalColor.darkGray)
                item.setToolTip(i18n.t("Файл не найден: {path}").format(path=track.path))
            self.list.addItem(item)
        if items:
            self.list.setCurrentRow(max(0, min(selected, len(items) - 1)))
        self.count.setText(i18n.t("{n} песен").format(n=len(items)) if items else
                           i18n.t("Пока пусто — добавь первые песни"))
        self._mark_current()

    def _mark_current(self) -> None:
        track = self._player.current()
        for row in range(self.list.count()):
            item = self.list.item(row)
            font = item.font()
            font.setBold(track is not None and item.data(Qt.ItemDataRole.UserRole) == track.path)
            item.setFont(font)

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, i18n.t("Песни для плейлиста"),
                                                str(Path.home() / "Music"), _AUDIO_FILTER)
        self._added(playlist.add(files))

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, i18n.t("Папка с музыкой"), str(Path.home() / "Music"))
        if folder:
            self._added(playlist.add([folder]))

    def _added(self, count: int) -> None:
        self._render_list()
        if count:
            self.count.setText(i18n.t("Добавлено: {n}").format(n=count))

    def _remove_selected(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            playlist.remove(str(item.data(Qt.ItemDataRole.UserRole)))
            self._render_list()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.list and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Delete:
            self._remove_selected()
            return True
        return super().eventFilter(watched, event)

    # ---------------------------------------------------------------- перетаскивание

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self._added(playlist.add(paths))
        event.acceptProposedAction()
