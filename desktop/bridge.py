"""Мост между потоком ассистента и потоком интерфейса.

Ассистент публикует события в core.bus из своего потока; Bridge превращает их
в сигналы Qt, которые доставляются в GUI-поток очередью — без гонок и блокировок.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    state_changed = Signal(str)
    level_changed = Signal(float)
    viseme_changed = Signal(dict)        # положение рта: губы персонажа идут за голосом
    message_received = Signal(str, str)  # kind, text
    speech_progress = Signal(str)        # реплика по мере произнесения — для субтитров
    emotion_changed = Signal(str, str, float)  # плоский ключ, трёхмерный ключ, секунды
    event = Signal(dict)                 # сырое событие: нужно окну видеосвязи

    def publish(self, payload: dict[str, Any]) -> None:
        """Вызывается из потока ассистента. Только эмит сигналов — ничего тяжёлого."""
        kind = payload.get("type")
        self.event.emit(dict(payload))
        if kind == "viseme":
            self.viseme_changed.emit({key: value for key, value in payload.items()
                                      if key not in ("type", "ts")})
        elif kind == "state":
            self.state_changed.emit(str(payload.get("state", "idle")))
            self.level_changed.emit(float(payload.get("level", 0.0)))
        elif kind == "level":
            self.level_changed.emit(float(payload.get("level", 0.0)))
        elif kind == "message":
            self.message_received.emit(str(payload.get("kind", "system")), str(payload.get("text", "")))
        elif kind == "speech":
            # реплика по ходу произнесения: субтитр набирается вместе с голосом
            self.speech_progress.emit(str(payload.get("text", "")))
        elif kind == "emotion":
            self.emotion_changed.emit(
                str(payload.get("key", "speaking")),
                str(payload.get("shape", "smile")),
                float(payload.get("seconds", 2.4)),
            )
