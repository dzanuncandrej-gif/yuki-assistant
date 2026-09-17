"""Голосовой слой компаньона поверх core.tts.

Отдельный модуль нужен, чтобы «кто говорит» не было зашито в интерфейс: панель
просит голос у этого слоя, а он уже решает, какой профиль поставить ассистенту
и как проговорить текст. Позже сюда же встанут эмоциональные интонации и
собственные реплики персонажа.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping

from core import voices


class CompanionVoice:
    """Женский голос персонажа: выбор профиля, проба, произнесение реплик."""

    def __init__(self, assistant: Any, settings: Mapping[str, Any] | None = None) -> None:
        self._assistant = assistant
        self._key = str((settings or {}).get("voice", "mira"))
        self._enabled = bool((settings or {}).get("enabled", True))
        self._on_speak: Callable[[str], None] | None = None

    # ---------------------------------------------------------------- профиль

    @staticmethod
    def catalog() -> tuple[voices.Profile, ...]:
        """Голоса, которые подходят компаньону: женские и живые."""
        available = {profile.key: profile for profile in voices.catalog()}
        return tuple(available[key] for key in voices.COMPANION_KEYS if key in available)

    @property
    def key(self) -> str:
        return self._key

    @property
    def profile(self) -> voices.Profile | None:
        return voices.get(self._key)

    def use(self, key: str) -> str:
        """Ставит голос персонажа основным голосом ассистента."""
        self._key = key
        if not self._enabled:
            return key
        threading.Thread(
            target=self._assistant.set_voice, args=(key,), name="companion-voice", daemon=True
        ).start()
        return key

    def preview(self, key: str) -> None:
        threading.Thread(
            target=self._assistant.preview_voice, args=(key,), name="companion-voice-preview", daemon=True
        ).start()

    # ---------------------------------------------------------------- речь

    def set_enabled(self, enabled: bool) -> None:
        """Выключенный компаньон возвращает ассистенту его собственный голос."""
        self._enabled = enabled
        target = self._key if enabled else voices.DEFAULT
        threading.Thread(
            target=self._assistant.set_voice, args=(target,), name="companion-voice-mode", daemon=True
        ).start()

    def say(self, text: str) -> None:
        """Произносит реплику от лица персонажа, не блокируя интерфейс."""
        if not text.strip():
            return
        if self._on_speak is not None:
            self._on_speak(text)
        threading.Thread(
            target=self._assistant.say, args=(text,), name="companion-say", daemon=True
        ).start()

    def bind_display(self, callback: Callable[[str], None]) -> None:
        """Куда дублировать текст реплики — например, в облако над персонажем."""
        self._on_speak = callback
