"""Жизнь персонажа: превращает состояние ассистента в непрерывное движение.

Аниматор ничего не рисует. Он держит текущую позу и на каждом кадре подтягивает
её к цели: эмоция задаёт «куда», пружины и шумы — «как». Отсюда берутся дыхание,
моргание, микродвижения взгляда, инерция волос и синхронизация рта с голосом.
"""

from __future__ import annotations

import math
import random
import time

from . import emotions
from .rig import Pose


def _approach(current: float, target: float, rate: float) -> float:
    """Экспоненциальное сближение: чем дальше цель, тем быстрее движение."""
    return current + (target - current) * min(1.0, max(0.0, rate))


class Spring:
    """Пружина с затуханием — ею качаются волосы и корпус."""

    def __init__(self, stiffness: float = 0.16, damping: float = 0.78) -> None:
        self.value = 0.0
        self.velocity = 0.0
        self._stiffness = stiffness
        self._damping = damping

    def push(self, force: float) -> None:
        self.velocity += force

    def step(self, target: float = 0.0) -> float:
        self.velocity += (target - self.value) * self._stiffness
        self.velocity *= self._damping
        self.value += self.velocity
        return self.value


class Animator:
    """Держит позу персонажа. Снаружи задаются состояние, громкость и эмоция."""

    def __init__(self) -> None:
        self.pose = Pose()
        self._emotion = emotions.get("neutral")
        self._override: tuple[emotions.Emotion, float] | None = None  # эмоция и её срок
        self._state = "idle"
        self._level = 0.0
        self._level_smooth = 0.0

        self._started = time.monotonic()
        self._last = self._started
        self._next_blink = self._started + 2.5
        self._blink_phase = 0.0
        self._next_saccade = self._started + 1.2
        self._gaze = (0.0, 0.0)
        self._gaze_target = (0.0, 0.0)
        self._next_gesture = self._started + 12.0
        self._ear_twitch_at = self._started + 6.0

        self._hair = Spring(stiffness=0.10, damping=0.86)
        self._body = Spring(stiffness=0.06, damping=0.90)
        self._head_x = 0.0
        self._head_y = 0.0
        self._look_at: tuple[float, float] | None = None
        self._speaking_energy = 0.0
        self.follow_cursor = True
        self.idle_motion = True
        self.lip_sync = True

    # ---------------------------------------------------------------- внешнее API

    def set_state(self, state: str) -> None:
        """Состояние ассистента: idle | listening | thinking | speaking."""
        if state == self._state:
            return
        self._state = state
        self._emotion = emotions.emotion_for(state)
        self._hair.push(0.5 if state == "speaking" else 0.3)
        if state == "speaking":
            self._next_gesture = time.monotonic() + random.uniform(1.5, 4.0)

    def set_level(self, level: float) -> None:
        """Громкость 0..1: при речи открывает рот, при слушании качает ушами."""
        self._level = max(0.0, min(1.0, float(level)))

    def play(self, key: str, seconds: float = 2.4) -> None:
        """Показать эмоцию поверх состояния: реакция на событие, а не фон."""
        emotion = emotions.get(key)
        self._override = (emotion, time.monotonic() + seconds)
        self._hair.push(0.8)
        self._body.push(0.5)

    def look_at(self, x: float, y: float) -> None:
        """Куда смотреть: -1..1 по каждой оси. None-режим вернёт свободный взгляд."""
        self._look_at = (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))

    def release_look(self) -> None:
        self._look_at = None

    @property
    def emotion(self) -> emotions.Emotion:
        override = self._override
        if override is not None and time.monotonic() < override[1]:
            return override[0]
        return self._emotion

    # ---------------------------------------------------------------- кадр

    def step(self) -> Pose:
        now = time.monotonic()
        self._last = now
        phase = now - self._started

        emotion = self.emotion
        if self._override is not None and now >= self._override[1]:
            self._override = None

        pose = self.pose
        energy = emotion.energy if self.idle_motion else 0.4

        self._level_smooth = _approach(
            self._level_smooth, self._level, 0.5 if self._level > self._level_smooth else 0.16
        )

        self._breathe(pose, phase, energy)
        self._blink(pose, now, emotion)
        self._gaze_step(pose, now, phase)
        self._mouth(pose, phase, emotion)
        self._face(pose, emotion)
        self._hair_step(pose, phase, energy)
        self._gestures(pose, now, emotion, phase)

        pose.glow = _approach(pose.glow, 0.35 + 0.65 * (0.3 + 0.7 * self._level_smooth), 0.08)
        return pose

    # ---------------------------------------------------------------- слои движения

    def _breathe(self, pose: Pose, phase: float, energy: float) -> None:
        """Дыхание и лёгкое покачивание: без них фигура выглядит мёртвой картинкой."""
        breath = math.sin(phase * 1.05 * energy) * 0.6 + math.sin(phase * 0.43) * 0.4
        pose.breath = _approach(pose.breath, breath, 0.2)

        sway = math.sin(phase * 0.37 * energy) * 0.6 + math.sin(phase * 0.19 + 1.3) * 0.4
        pose.body_sway = _approach(pose.body_sway, sway * 0.8 + self._body.step(), 0.14)
        pose.arm_swing = _approach(pose.arm_swing, breath * 0.8, 0.1)
        pose.lean = _approach(pose.lean, self.emotion.lean, 0.05)

    def _blink(self, pose: Pose, now: float, emotion: emotions.Emotion) -> None:
        """Моргание: быстрое закрытие, чуть более медленное открытие, иногда двойное."""
        if now >= self._next_blink:
            elapsed = now - self._next_blink
            if elapsed < 0.07:
                pose.blink = elapsed / 0.07
            elif elapsed < 0.16:
                pose.blink = 1.0 - (elapsed - 0.07) / 0.09
            else:
                pose.blink = 0.0
                gap = random.uniform(1.8, 5.4)
                if random.random() < 0.18:      # изредка моргает дважды подряд
                    gap = 0.28
                self._next_blink = now + gap
        else:
            pose.blink = _approach(pose.blink, 0.0, 0.4)

        pose.eye_open = _approach(pose.eye_open, emotion.eye_open, 0.12)
        pose.eye_round = _approach(pose.eye_round, emotion.eye_round, 0.12)
        pose.wink = _approach(pose.wink, 1.0 if emotion.key == "wink" else 0.0, 0.2)

    def _gaze_step(self, pose: Pose, now: float, phase: float) -> None:
        """Взгляд: следит за курсором, а между делом живёт микродвижениями."""
        if self._look_at is not None and self.follow_cursor:
            target = self._look_at
        else:
            if now >= self._next_saccade:
                self._gaze_target = (random.uniform(-0.6, 0.6), random.uniform(-0.4, 0.4))
                self._next_saccade = now + random.uniform(1.1, 3.4)
            target = self._gaze_target

        drift_x = math.sin(phase * 0.8) * 0.04
        drift_y = math.cos(phase * 0.6) * 0.03
        self._gaze = (
            _approach(self._gaze[0], target[0] + drift_x, 0.18),
            _approach(self._gaze[1], target[1] + drift_y, 0.18),
        )
        pose.look_x, pose.look_y = self._gaze

        # голова тянется за взглядом, но заметно ленивее — так движение читается живым
        previous_x = self._head_x
        self._head_x = _approach(self._head_x, self._gaze[0] * 0.55, 0.05)
        self._head_y = _approach(self._head_y, self._gaze[1] * 0.5, 0.05)
        self._hair.push((self._head_x - previous_x) * -1.4)

        pose.head_yaw = self._head_x
        pose.head_pitch = -self._head_y
        tilt_target = self.emotion.tilt + math.sin(phase * 0.28) * 0.14
        pose.head_tilt = _approach(pose.head_tilt, tilt_target, 0.05)

    def _mouth(self, pose: Pose, phase: float, emotion: emotions.Emotion) -> None:
        """Липсинк: рот открывается по громкости собственной речи, плюс дрожь гласных."""
        base = emotion.mouth_open
        if self._state == "speaking" and self.lip_sync:
            vibrato = 0.5 + 0.5 * math.sin(phase * 18.0)
            target = min(1.0, base + self._level_smooth * (0.55 + 0.45 * vibrato) * 1.5)
            self._speaking_energy = _approach(self._speaking_energy, 1.0, 0.1)
        else:
            target = base
            self._speaking_energy = _approach(self._speaking_energy, 0.0, 0.05)
        pose.mouth_open = _approach(pose.mouth_open, target, 0.45 if target > pose.mouth_open else 0.2)
        pose.smile = _approach(pose.smile, emotion.smile, 0.1)

    def _face(self, pose: Pose, emotion: emotions.Emotion) -> None:
        pose.brow_raise = _approach(pose.brow_raise, emotion.brow_raise, 0.12)
        pose.brow_angle = _approach(pose.brow_angle, emotion.brow_angle, 0.12)
        pose.blush = _approach(pose.blush, emotion.blush, 0.06)
        pose.sweat = _approach(pose.sweat, emotion.sweat, 0.08)
        pose.sparkle = _approach(pose.sparkle, emotion.sparkle, 0.08)
        pose.pupil = _approach(pose.pupil, 1.0 + 0.18 * emotion.sparkle - 0.15 * emotion.sweat, 0.08)

    def _hair_step(self, pose: Pose, phase: float, energy: float) -> None:
        """Волосы качаются с задержкой относительно головы — это и читается как «живое»."""
        drift = math.sin(phase * 0.6 * energy) * 0.25 + math.sin(phase * 0.27) * 0.15
        pose.hair_sway = _approach(pose.hair_sway, self._hair.step(drift), 0.3)
        pose.hair_lift = _approach(pose.hair_lift, abs(self._hair.velocity) * 6.0, 0.2)

    def _gestures(self, pose: Pose, now: float, emotion: emotions.Emotion, phase: float) -> None:
        """Жесты: приветственный взмах и подёргивание ушей — редкие, но заметные."""
        wave_target = emotion.wave
        if wave_target > 0.05:
            wave_target *= 0.5 + 0.5 * math.sin(phase * 6.0)
        pose.wave = _approach(pose.wave, max(0.0, wave_target), 0.12)

        pose.ear_perk = _approach(pose.ear_perk, emotion.ear_perk, 0.08)
        if now >= self._ear_twitch_at:
            pose.ear_twitch = 1.0
            self._ear_twitch_at = now + random.uniform(4.0, 12.0)
        pose.ear_twitch = _approach(pose.ear_twitch, 0.0, 0.18)
