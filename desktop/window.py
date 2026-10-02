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

from . import webpanel
from .bridge import Bridge
from .call import CallWindow
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
        # Командный центр на WebGL, если движок есть; прежние виджеты остаются
        # запасным вариантом и живут невидимыми — на них завязаны трей и самопроверка.
        hub = None
        legacy = dialog  # без ссылки Qt удалит страницу вместе с виджетами трея
        pages: dict[str, QWidget] = {}
        if webpanel.ENGINE_READY:
            from .agent_view import AgentView
            from .hub import HubView
            from .music_view import MusicView

            hub = HubView(assistant, bridge)
            dialog = hub
            pages = {"agent": AgentView(assistant), "playlist": MusicView()}

        super().__init__(
            shell.store,
            shell.actions(),
            extra=(("dialog", i18n.t("◆  ДИАЛОГ"), i18n.t("Диалог"),
                    i18n.t("Переписка с Юки, микрофон и уровень голоса"), dialog),),
            on_call=lambda: self.start_call(),
            pages=pages,
        )
        self._assistant = assistant
        self._bridge = bridge
        self._shell = shell
        self._quitting = False
        self._call: CallWindow | None = None
        self._onboarding = None
        self.hub = hub
        self._legacy_dialog = legacy
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

        # командная строка поверх всех окон: Ctrl+Alt+Пробел
        from .palette import CommandPalette

        self.palette = CommandPalette(self._assistant)
        self.palette_hotkey = GlobalHotkey("<ctrl>+<alt>+<space>")
        self.palette_hotkey.triggered.connect(self.palette.toggle)
        self.palette_hotkey.start()

        if self.hub is not None:
            self.hub.call_requested.connect(self.start_call)
            self.hub.mute_changed.connect(self._sync_mute)
        self._bridge.event.connect(self._on_ui_event)

        # живая карточка статуса в боковой панели
        self._bridge.state_changed.connect(self._on_status_state)
        self._bridge.level_changed.connect(self.status_card.set_level)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_model)
        self._status_timer.start(2500)
        QTimer.singleShot(400, self._refresh_model)

    def _install_window_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.composer.input.setFocus)
        QShortcut(QKeySequence("Ctrl+Space"), self, activated=self._assistant.interrupt)
        QShortcut(QKeySequence("Ctrl+J"), self, activated=self.toggle_companion)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._assistant.reset)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.quit)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.start_call)
        QShortcut(QKeySequence("F1"), self, activated=self.start_onboarding)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(QIcon(make_tray_icon()), self)
        self.tray.setToolTip("Юки")

        menu = QMenu()
        self._action_show = QAction(i18n.t("Показать пульт"), self)
        self._action_show.triggered.connect(self.show_from_tray)
        self._action_mic = QAction(i18n.t("Выключить микрофон"), self)
        self._action_mic.setCheckable(True)
        self._action_mic.toggled.connect(self._on_tray_mic)
        action_call = QAction(i18n.t("Видеосвязь (Ctrl+D)"), self)
        action_call.triggered.connect(self.start_call)
        action_learn = QAction(i18n.t("Обучение (F1)"), self)
        action_learn.triggered.connect(self.start_onboarding)
        action_companion = QAction(i18n.t("Персонаж на столе (Ctrl+J)"), self)
        action_companion.triggered.connect(self.toggle_companion)
        action_silence = QAction(i18n.t("Замолчать (Ctrl+Space)"), self)
        action_silence.triggered.connect(self._assistant.interrupt)
        action_reset = QAction(i18n.t("Очистить контекст (Ctrl+R)"), self)
        action_reset.triggered.connect(self._assistant.reset)
        action_quit = QAction(i18n.t("Выход"), self)
        action_quit.triggered.connect(self.quit)

        menu.addAction(self._action_show)
        menu.addAction(action_call)
        menu.addAction(action_learn)
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

    # ---------------------------------------------------------------- звонок

    def start_call(self) -> None:
        """Открывает видеосвязь; если звонок уже идёт — просто поднимает его окно."""
        if self._call is not None:
            self._call.raise_()
            self._call.activateWindow()
            return
        if not webpanel.ENGINE_READY:
            self.log.add_message("error", i18n.t("Для видеосвязи нужен QtWebEngine (pip install PySide6-Addons)."))
            return
        muted = bool(getattr(self._assistant, "_muted", None) and self._assistant._muted.is_set())
        call = CallWindow(self._assistant, self._bridge, muted=muted)
        call.ended.connect(self._on_call_ended)
        call.mute_changed.connect(self._sync_mute)
        self._call = call
        screen = self.screen() or QApplication.primaryScreen()
        call.start(screen.geometry())

    def start_onboarding(self) -> None:
        """Знакомство с Юки: проверка системы, голос, имя и обучение на практике."""
        if not webpanel.ENGINE_READY:
            return
        if self._onboarding is not None:
            self._onboarding.raise_()
            self._onboarding.activateWindow()
            return
        from .onboarding import OnboardingWindow

        window = OnboardingWindow(self._assistant, self._bridge, self._store)
        window.closed.connect(lambda: setattr(self, "_onboarding", None))
        window.call_requested.connect(self.start_call)
        self._onboarding = window
        window.open()

    def end_call(self) -> None:
        if self._call is not None:
            self._call.hang_up()

    def _on_call_ended(self) -> None:
        self._call = None

    def _on_ui_event(self, payload: dict) -> None:
        if payload.get("type") != "ui":
            return
        action = payload.get("action")
        if action == "start_call":
            self.start_call()
        elif action == "end_call":
            self.end_call()
        elif action == "open_section":
            self.open_section(str(payload.get("section") or ""))
            if not self.isVisible() or self.isMinimized():
                self.show_from_tray()
        elif action == "quit_later":
            # новый экземпляр с правами уже запрошен — даём договорить и уходим
            QTimer.singleShot(4500, self.quit)

    def _on_status_state(self, state: str) -> None:
        muted = bool(getattr(self._assistant, "_muted", None) and self._assistant._muted.is_set())
        self.status_card.set_state("muted" if muted and state != "speaking" else state)

    def _refresh_model(self) -> None:
        agent = getattr(self._assistant, "_agent", None)
        if agent is None:
            return
        online = bool(getattr(agent, "_online", False))
        name = agent.model or str(getattr(agent, "_cfg", {}).get("model", "—"))
        self.status_card.set_model(f"{name}  ·  локально", online)

    def _sync_mute(self, muted: bool) -> None:
        """Микрофон выключили в пульте или в звонке — трей и прежние виджеты в курсе."""
        self._action_mic.blockSignals(True)
        self._action_mic.setChecked(muted)
        self._action_mic.blockSignals(False)
        self._action_mic.setText(i18n.t("Включить микрофон") if muted else i18n.t("Выключить микрофон"))
        self.composer.set_muted(muted)
        if self._shell.panel is not None:
            self._shell.panel.set_muted(muted)
        self.status_card.set_state("muted" if muted else "idle")

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
        if self._call is not None:
            self._call.hang_up()
        self._shell.stop()
        self.hotkey.stop()
        self.palette_hotkey.stop()
        bus.bus.unsubscribe_callback(self._bridge.publish)
        self._assistant.stop()
        self.tray.hide()
        QApplication.quit()
