"""Эмоции персонажа: цель, к которой аниматор плавно ведёт позу.

Эмоция — это не картинка, а набор смещений: насколько открыты глаза, как подняты
брови, какая улыбка, есть ли румянец. Аниматор смешивает текущее состояние с
целевым, поэтому переход между эмоциями всегда плавный.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Emotion:
    key: str
    title: str
    eye_open: float = 1.0        # 1 — обычные глаза, 0 — закрытые
    eye_round: float = 1.0       # выше — глаза шире, «удивление»
    brow_raise: float = 0.0      # -1 нахмурена, 1 подняты
    brow_angle: float = 0.0      # -1 «домиком» (грусть), 1 углом вниз (злость)
    smile: float = 0.15          # -1 уголки вниз, 1 широкая улыбка
    mouth_open: float = 0.0      # базовое приоткрытие рта
    blush: float = 0.0
    sparkle: float = 0.0         # блеск в глазах
    sweat: float = 0.0           # капля у виска
    tilt: float = 0.0            # наклон головы
    energy: float = 1.0          # темп дыхания и покачиваний
    ear_perk: float = 0.0        # уши торчком (интерес) или прижаты (грусть)
    wave: float = 0.0            # приветственный жест рукой
    lean: float = 0.0            # наклон корпуса вперёд/назад


NEUTRAL: Final = Emotion("neutral", "спокойна")

EMOTIONS: Final[dict[str, Emotion]] = {
    "neutral": NEUTRAL,
    "happy": Emotion(
        "happy", "радуется", eye_open=0.92, brow_raise=0.25, smile=0.75,
        mouth_open=0.10, blush=0.28, sparkle=0.55, tilt=0.10, energy=1.15, ear_perk=0.5,
    ),
    "joy": Emotion(
        "joy", "смеётся", eye_open=0.12, brow_raise=0.4, smile=1.0, mouth_open=0.45,
        blush=0.45, sparkle=0.8, tilt=0.16, energy=1.4, ear_perk=0.75, lean=0.2,
    ),
    "surprised": Emotion(
        "surprised", "удивлена", eye_open=1.0, eye_round=1.28, brow_raise=0.9,
        smile=0.0, mouth_open=0.42, sparkle=0.35, tilt=-0.06, energy=1.3, ear_perk=1.0, lean=-0.15,
    ),
    "thinking": Emotion(
        "thinking", "думает", eye_open=0.78, brow_raise=-0.2, brow_angle=0.18,
        smile=0.05, sparkle=0.1, tilt=0.22, energy=0.85, ear_perk=-0.2,
    ),
    "listening": Emotion(
        "listening", "слушает", eye_open=1.05, brow_raise=0.2, smile=0.28,
        sparkle=0.3, tilt=-0.08, energy=1.05, ear_perk=0.9, lean=0.12,
    ),
    "speaking": Emotion(
        "speaking", "говорит", eye_open=0.98, brow_raise=0.12, smile=0.42,
        blush=0.12, sparkle=0.25, energy=1.1, ear_perk=0.35,
    ),
    "shy": Emotion(
        "shy", "смущена", eye_open=0.7, brow_raise=0.3, brow_angle=-0.3, smile=0.35,
        blush=0.85, sparkle=0.4, sweat=0.2, tilt=0.2, energy=0.9, ear_perk=-0.4,
    ),
    "sad": Emotion(
        "sad", "грустит", eye_open=0.72, brow_raise=-0.1, brow_angle=-0.65, smile=-0.5,
        blush=0.1, tilt=-0.18, energy=0.75, ear_perk=-0.9, lean=-0.1,
    ),
    "sleepy": Emotion(
        "sleepy", "дремлет", eye_open=0.35, brow_raise=-0.15, smile=0.1,
        mouth_open=0.05, tilt=0.26, energy=0.6, ear_perk=-0.7,
    ),
    "wink": Emotion(
        "wink", "подмигивает", eye_open=0.95, brow_raise=0.35, smile=0.7,
        blush=0.3, sparkle=0.6, tilt=0.14, energy=1.2, ear_perk=0.6, wave=0.35,
    ),
    "greeting": Emotion(
        "greeting", "здоровается", eye_open=1.0, brow_raise=0.4, smile=0.85,
        mouth_open=0.2, blush=0.2, sparkle=0.6, tilt=0.08, energy=1.25, ear_perk=0.8, wave=1.0,
    ),
    "alert": Emotion(
        "alert", "насторожилась", eye_open=1.02, eye_round=1.12, brow_raise=0.1,
        brow_angle=0.3, smile=-0.05, sweat=0.25, energy=1.2, ear_perk=1.0,
    ),
}

# состояние ассистента → эмоция по умолчанию
STATE_EMOTION: Final[dict[str, str]] = {
    "idle": "neutral",
    "listening": "listening",
    "thinking": "thinking",
    "speaking": "speaking",
}


def emotion_for(state: str) -> Emotion:
    return EMOTIONS[STATE_EMOTION.get(state, "neutral")]


def get(key: str) -> Emotion:
    return EMOTIONS.get(key, NEUTRAL)


def names() -> tuple[str, ...]:
    return tuple(EMOTIONS)
