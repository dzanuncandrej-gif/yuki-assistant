"""Оболочка нового интерфейса: панель компаньона, меню управления и их связи.

Слой намеренно тонкий. Он знает про ассистента ровно то, что нужно, чтобы
передать ему изменение настроек, и про виджеты — чтобы показать состояние.
Вся «умная» логика остаётся в core, вся отрисовка — в companion и menu.
"""

from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtCore import QObject, QTimer

from core import bus
from core.idle import IdlePersonality, Remark

from .bridge import Bridge
from .companion.panel import CompanionPanel
from .companion.voice import CompanionVoice
from .menu.control_menu import ControlMenu
from .menu.pages import Actions
from .menu.settings import SettingsStore


class Shell(QObject):
    """Хозяин панели и меню: создаёт их лениво и держит настройки в согласии."""

    def __init__(self, assistant: Any, bridge: Bridge, cfg: Mapping[str, Any],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._bridge = bridge
        self.store = SettingsStore(cfg, self)
        self.voice = CompanionVoice(assistant, self.store.section("companion"))
        self.panel: CompanionPanel | None = None
        self.menu: ControlMenu | None = None

        section = self.store.section("companion")
        self.idle = IdlePersonality(
            self._say_idle,
            self._show_idle,
            enabled=bool(section.get("idle_talk", True)),
            quiet_after=float(section.get("idle_talk_minutes", 15)) * 60.0,
        )
        # редкая проверка: реплика и так приходит раз в десятки минут
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._idle_tick)
        self._idle_timer.start(20_000)

        self._bridge.state_changed.connect(self._on_state)
        self._bridge.level_changed.connect(self._on_level)
        self._bridge.viseme_changed.connect(self._on_viseme)
        self._bridge.message_received.connect(self._on_message)
        self._bridge.speech_progress.connect(self._on_speech)
        self._bridge.emotion_changed.connect(self._on_emotion)
        self._bridge.event.connect(self._on_event)
        self.store.section_changed.connect(self._on_section_changed)

    # ---------------------------------------------------------------- панель

    @property
    def companion_enabled(self) -> bool:
        return bool(self.store.get("companion", "enabled", True))

    def ensure_panel(self) -> CompanionPanel:
        if self.panel is None:
            panel = CompanionPanel(self.store.section("companion"))
            panel.menu_requested.connect(self.open_menu)
            panel.mic_toggled.connect(self._assistant.set_muted)
            panel.hidden.connect(lambda: self.store.set("companion", "enabled", False))
            self.panel = panel
        return self.panel

    def show_panel(self) -> None:
        panel = self.ensure_panel()
        panel.apply_settings(self.store.section("companion"))
        panel.show()
        panel.greet()
        self.store.set("companion", "enabled", True)

    def hide_panel(self) -> None:
        if self.panel is not None:
            self.panel.hide()
        self.store.set("companion", "enabled", False)

    def toggle_panel(self) -> None:
        if self.panel is not None and self.panel.isVisible():
            self.hide_panel()
        else:
            self.show_panel()

    def start(self) -> None:
        """Поднимает панель, если она включена в настройках."""
        if self.companion_enabled:
            self.show_panel()

    def stop(self) -> None:
        if self.panel is not None:
            self.store.set("companion", "position", self.panel.position())
            self.panel.close()
        if self.menu is not None:
            self.menu.close()
        self.store.flush()

    # ---------------------------------------------------------------- меню

    def open_menu(self, section: str | None = None) -> None:
        if self.menu is None:
            self.menu = ControlMenu(self.store, self.actions())
        if section:
            self.menu.open_section(section)
        self.menu.show_centered(self.panel)

    def actions(self) -> Actions:
        return Actions(
            apply_voice=self.voice.use,
            preview_voice=self.voice.preview,
            toggle_companion=lambda enabled: self.show_panel() if enabled else self.hide_panel(),
            companion_updated=self._refresh_panel,
            reset_context=self._assistant.reset,
            say_test=self.voice.say,
            diagnostics=self._diagnostics,
            extras={
                "say": self.voice.say,
                "dictate_message": self._dictate_message,
            },
        )

    def _dictate_message(self, deliver) -> None:  # noqa: ANN001 — Callable[[str], None]
        """Продиктовать текст сообщения голосом.

        Юки спрашивает вслух и слушает следующую фразу. Реплика не уходит в агента:
        она целиком становится текстом сообщения, иначе «передай, что я опоздаю»
        было бы понято как команда и превратилось бы в действие, а не в текст.
        """
        self._dictation = deliver
        self.voice.say("Что мне написать?")
        self._assistant.capture_next(self._on_dictated)

    def _on_dictated(self, text: str) -> None:
        deliver, self._dictation = getattr(self, "_dictation", None), None
        if deliver is not None and text.strip():
            deliver(text.strip())
            self.voice.say("Записала. Проверь текст и нажми «Отправить».")

    def _diagnostics(self) -> str:
        parts = [
            f"голос: {self._assistant.voice_key}",
            f"панель компаньона: {'показана' if self.panel is not None and self.panel.isVisible() else 'скрыта'}",
            f"состояние: {bus.bus.state}",
        ]
        return " · ".join(parts)

    # ---------------------------------------------------------------- события

    def _refresh_panel(self) -> None:
        if self.panel is not None:
            self.panel.apply_settings(self.store.section("companion"))

    def _on_section_changed(self, section: str, values: dict[str, Any]) -> None:
        if section != "companion":
            return
        self.idle.enabled = bool(values.get("idle_talk", True))
        self.idle.quiet_after = max(60.0, float(values.get("idle_talk_minutes", 15)) * 60.0)
        self._refresh_panel()

    # ---------------------------------------------------------------- своя жизнь

    def _idle_tick(self) -> None:
        """Персонаж заговаривает сам — но только в полной тишине."""
        panel = self.panel
        if panel is None or not panel.isVisible():
            return
        # занят не только разговор: пока ассистент думает или слушает, влезать нельзя
        self.idle.tick(busy=bus.bus.state != bus.IDLE)

    def _say_idle(self, text: str) -> None:
        self.voice.say(text)

    def _show_idle(self, remark: Remark) -> None:
        panel = self.panel
        if panel is None:
            return
        panel.character.play_emotion(remark.emotion, 3.0)
        if remark.gesture and hasattr(panel.character, "react"):
            panel.character.play_gesture(remark.gesture)

    def _on_state(self, state: str) -> None:
        if state != bus.IDLE:
            self.idle.touch()   # любая работа ассистента сбрасывает отсчёт тишины
        if self.panel is not None:
            self.panel.on_state(state)

    def _on_level(self, level: float) -> None:
        if self.panel is not None:
            self.panel.on_level(level)

    def _on_viseme(self, shape: dict[str, float]) -> None:
        if self.panel is not None:
            self.panel.on_viseme(shape)

    def _on_message(self, kind: str, text: str) -> None:
        if kind in ("user", "assistant"):
            self.idle.touch()
        if self.panel is not None:
            self.panel.on_message(kind, text)

    def _on_speech(self, text: str) -> None:
        """Субтитр набирается вместе с голосом, а не появляется после реплики."""
        self.idle.touch()
        if self.panel is not None:
            self.panel.on_speech(text)

    def _on_emotion(self, key: str, shape: str, seconds: float) -> None:
        """Настроение реплики: лицо персонажа меняется вместе с тем, что она говорит."""
        if self.panel is not None:
            self.panel.on_emotion(key, shape, seconds)

    def _on_event(self, payload: dict[str, Any]) -> None:
        """Событие из ядра: жест «три пальца» показывает или прячет компаньона."""
        if payload.get("type") != "ui":
            return
        if payload.get("action") == "toggle_companion":
            self.toggle_panel()
