"""Главное окно — центр управления.

Раньше здесь была сфера во весь экран, а настройки жили в отдельном окне,
которое приходилось звать сочетанием клавиш. Теперь наоборот: приложение сразу
открывается пультом с боковой навигацией, а живой персонаж стоит на рабочем
столе отдельным прозрачным окном и в главное окно не встраивается.

Само оформление пульта — в `menu/control_menu.py`. Здесь к нему добавлены
раздел диалога, значок в трее, горячие клавиши и жизненный цикл приложения.
"""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core import bus, i18n

from .bridge import Bridge
from .hotkey import GlobalHotkey
from .menu.control_menu import ControlMenu
from .theme import STATE_LABELS
from .widgets import ChatLog, Composer, LevelMeter, MetricsLabel, VoiceSelector, make_tray_icon


def _build_dialog() -> tuple[ChatLog, LevelMeter, Composer, VoiceSelector, QWidget]:
    """Раздел диалога: уровень голоса, переписка, строка ввода и подвал."""
    log, meter, composer, voices = ChatLog(), LevelMeter(), Composer(), VoiceSelector()

    footer = QWidget()
    row = QHBoxLayout(footer)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(14)
    row.addWidget(voices)
    row.addStretch(1)
    row.addWidget(MetricsLabel())

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 8, 0)
    layout.setSpacing(12)
    layout.addWidget(meter)
    layout.addWidget(log, 1)
    layout.addWidget(composer)
    layout.addWidget(footer)
    return log, meter, composer, voices, page


class MainWindow(ControlMenu):
    """Пульт управления Юки: разделы настроек плюс живой диалог."""

    def __init__(self, assistant: Any, bridge: Bridge, shell: Any) -> None:
        # виджеты собираются до super(): обращаться к self раньше инициализации
        # QWidget нельзя — компоновка тогда не применяется и страница разъезжается
        log, meter, composer, voices, dialog = _build_dialog()

        super().__init__(
            shell.store,
            shell.actions(),
            extra=(("dialog", i18n.t("◆  ДИАЛОГ"), i18n.t("Диалог"),
                    i18n.t("Переписка с Юки, микрофон и уровень голоса"), dialog),),
        )
        self._assistant = assistant
        self._bridge = bridge
        self._shell = shell
        self._quitting = False
        self.log, self.meter, self.composer, self.voices = log, meter, composer, voices
        self.setWindowTitle("Юки")

        self.hotkey = GlobalHotkey()
        self._wire()
        self._build_tray()
        self._install_window_shortcuts()

    # ---------------------------------------------------------------- связи

    def _wire(self) -> None:
        self._bridge.state_changed.connect(self._on_state)
        self._bridge.level_changed.connect(self.meter.set_level)
        self._bridge.message_received.connect(self.log.add_message)

        self.composer.submitted.connect(self._on_text)
        self.composer.mic_toggled.connect(self._assistant.set_muted)

        self.voices.voice_changed.connect(self._on_voice)
        self.voices.preview_requested.connect(self._on_voice_preview)
        self.voices.set_current(self._assistant.voice_key)
        # голос могли сменить голосовой командой — держим список в согласии
        self._voice_sync = QTimer(self)
        self._voice_sync.timeout.connect(lambda: self.voices.set_current(self._assistant.voice_key))
        self._voice_sync.start(2000)

        self.hotkey.triggered.connect(self.toggle_visibility)
        self.hotkey.start()

    def _install_window_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.composer.input.setFocus)
        QShortcut(QKeySequence("Ctrl+Space"), self, activated=self._assistant.interrupt)
        QShortcut(QKeySequence("Ctrl+J"), self, activated=self.toggle_companion)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._assistant.reset)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.quit)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(QIcon(make_tray_icon()), self)
        self.tray.setToolTip("Юки")

        menu = QMenu()
        self._action_show = QAction(i18n.t("Показать пульт"), self)
        self._action_show.triggered.connect(self.show_from_tray)
        self._action_mic = QAction(i18n.t("Выключить микрофон"), self)
        self._action_mic.setCheckable(True)
        self._action_mic.toggled.connect(self._on_tray_mic)
        action_companion = QAction(i18n.t("Персонаж на столе (Ctrl+J)"), self)
        action_companion.triggered.connect(self.toggle_companion)
        action_silence = QAction(i18n.t("Замолчать (Ctrl+Space)"), self)
        action_silence.triggered.connect(self._assistant.interrupt)
        action_reset = QAction(i18n.t("Очистить контекст (Ctrl+R)"), self)
        action_reset.triggered.connect(self._assistant.reset)
        action_quit = QAction(i18n.t("Выход"), self)
        action_quit.triggered.connect(self.quit)

        menu.addAction(self._action_show)
        menu.addAction(action_companion)
        menu.addAction(self._action_mic)
        menu.addMenu(self._build_voice_menu(menu))
        menu.addAction(action_silence)
        menu.addAction(action_reset)
        menu.addSeparator()
        menu.addAction(action_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _build_voice_menu(self, parent: QMenu) -> QMenu:
        """Смена голоса из трея — окно для этого открывать не нужно."""
        from core import voices

        submenu = QMenu(i18n.t("Голос"), parent)
        for profile in voices.catalog():
            title = profile.title if profile.installed else f"{profile.title} {i18n.t('(нет файла)')}"
            action = QAction(f"{title} — {profile.character}", self)
            action.setEnabled(profile.installed)
            action.triggered.connect(lambda _=False, key=profile.key: self._on_voice(key))
            submenu.addAction(action)
        return submenu

    # ---------------------------------------------------------------- события

    def _on_state(self, state: str) -> None:
        self.meter.set_state(state)
        self.tray.setToolTip(f"Юки — {i18n.t(STATE_LABELS.get(state, state))}")

    def _on_text(self, text: str) -> None:
        # обращение к LLM блокирующее, поэтому уводим его из потока интерфейса
        threading.Thread(
            target=self._assistant.handle_text, args=(text,), name="jarvis-text", daemon=True
        ).start()

    def _on_voice(self, key: str) -> None:
        threading.Thread(
            target=self._assistant.set_voice, args=(key,), name="jarvis-voice", daemon=True
        ).start()

    def _on_voice_preview(self, key: str) -> None:
        threading.Thread(
            target=self._assistant.preview_voice, args=(key,), name="jarvis-voice-preview", daemon=True
        ).start()

    def _on_tray_mic(self, muted: bool) -> None:
        self._action_mic.setText(i18n.t("Включить микрофон") if muted else i18n.t("Выключить микрофон"))
        self.composer.set_muted(muted)
        if self._shell.panel is not None:
            self._shell.panel.set_muted(muted)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def toggle_companion(self) -> None:
        self._shell.toggle_panel()

    def open_control_menu(self) -> None:
        """Настройки теперь и есть главное окно — просто поднимаем его."""
        self.show_from_tray()

    # ---------------------------------------------------------------- окно

    def toggle_visibility(self) -> None:
        self.hide_to_tray() if self.isVisible() else self.show_from_tray()

    def hide_to_tray(self) -> None:
        self.hide()

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        """Крестик прячет пульт в трей: персонаж на столе продолжает жить."""
        self._store.flush()
        if self._quitting:
            super(ControlMenu, self).closeEvent(event)
            return
        event.ignore()
        self.hide_to_tray()

    def quit(self) -> None:
        self._quitting = True
        self._shell.stop()
        self.hotkey.stop()
        bus.bus.unsubscribe_callback(self._bridge.publish)
        self._assistant.stop()
        self.tray.hide()
        QApplication.quit()
