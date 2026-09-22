"""Жесты рукой: управление музыкой и громкостью без слов.

Камера уже смотрит на человека — грех этим не воспользоваться. Двадцать одна точка
руки от mediapipe превращается в понятный жест, а жест — в действие:

    ☝ указательный палец   — воспроизведение или пауза
    👌 «окей»              — режим громкости: расстояние между пальцами и есть громкость
    ✌ два пальца           — следующий трек
    ✋ раскрытая ладонь     — тишина: обрываю речь и ставлю паузу
    ✊ кулак                — выключить или включить микрофон

Жест должен продержаться несколько кадров и потом «остыть» — иначе случайное движение
рукой запускало бы музыку.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config

MODEL = config.ROOT / "models" / "face" / "hand_landmarker.task"

# индексы точек руки в разметке mediapipe
WRIST = 0
THUMB_TIP, THUMB_IP = 4, 3
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

NAMES = {
    "point": "указательный палец",
    "ok": "окей",
    "peace": "два пальца",
    "three": "три пальца",
    "palm": "раскрытая ладонь",
    "fist": "кулак",
}

HOLD_FRAMES = 4      # столько подряд жест должен подтвердиться
COOLDOWN_S = 2.5     # столько после срабатывания тот же жест игнорируется


def model_ready() -> bool:
    return MODEL.exists() and MODEL.stat().st_size > 100_000


def _distance(a: Any, b: Any) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _extended(marks: list[Any], tip: int, pip: int) -> bool:
    """Палец разогнут, если кончик дальше от запястья, чем средний сустав."""
    wrist = marks[WRIST]
    return _distance(marks[tip], wrist) > _distance(marks[pip], wrist) * 1.12


def hand_size(marks: list[Any]) -> float:
    """Размер ладони — им нормируются все расстояния, чтобы жест не зависел от дистанции."""
    return max(1e-4, _distance(marks[WRIST], marks[MIDDLE_MCP]))


def pinch(marks: list[Any]) -> float:
    """Насколько сведены большой и указательный пальцы: 0 — вместе, 1+ — широко."""
    return _distance(marks[THUMB_TIP], marks[INDEX_TIP]) / hand_size(marks)


def classify(marks: list[Any]) -> str:
    """Определяет жест по точкам руки. Пустая строка — ничего понятного."""
    if len(marks) < 21:
        return ""

    index = _extended(marks, INDEX_TIP, INDEX_PIP)
    middle = _extended(marks, MIDDLE_TIP, MIDDLE_PIP)
    ring = _extended(marks, RING_TIP, RING_PIP)
    pinky = _extended(marks, PINKY_TIP, PINKY_PIP)
    touching = pinch(marks) < 0.42

    if touching and middle and ring and pinky:
        return "ok"                       # 👌 кольцо из пальцев, остальные подняты
    if index and middle and ring and not pinky:
        return "three"                    # 🤟 три пальца — записать голос в телеграм
    if index and middle and not ring and not pinky:
        return "peace"                    # ✌
    if index and not middle and not ring and not pinky and not touching:
        return "point"                    # ☝
    if index and middle and ring and pinky:
        return "palm"                     # ✋
    if not index and not middle and not ring and not pinky:
        # положение большого пальца в кулаке зависит от человека, поэтому не учитываем
        return "fist"                     # ✊
    return ""


@dataclass
class Event:
    """Распознанный жест или изменение громкости пальцами."""

    kind: str                 # point | ok | peace | palm | fist | volume
    value: int = 0            # для volume — уровень 0..100
    label: str = ""


class HandReader:
    """Ищет руку в кадре и превращает её в события. Живёт внутри цикла камеры."""

    def __init__(self, on_event: Callable[[Event], None] | None = None) -> None:
        self.on_event = on_event
        self.gesture = ""          # что видно прямо сейчас
        self.last_fired = ""
        self.volume_mode = False
        self._detector: Any | None = None
        self._lock = threading.Lock()
        self._holding = ""
        self._held = 0
        self._cooldown: dict[str, float] = {}
        self._stamp = 0
        self._volume_at = 0.0
        self._volume_left = 0.0

    # ---------------------------------------------------------------- модель

    def ready(self) -> bool:
        return model_ready()

    def _open(self) -> Any:
        if self._detector is not None:
            return self._detector
        import mediapipe as mp  # noqa: F401
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        # модель отдаём буфером: путь проекта кириллический, а загрузчик сишный
        blob = Path(MODEL).read_bytes()
        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_buffer=blob),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.55,
            min_tracking_confidence=0.5,
        )
        self._detector = mp_vision.HandLandmarker.create_from_options(options)
        return self._detector

    def close(self) -> None:
        detector = self._detector
        self._detector = None
        if detector is not None:
            try:
                detector.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- кадр

    def process(self, frame: Any) -> str:
        """Разбирает кадр BGR и возвращает текущий жест."""
        import cv2
        import mediapipe as mp

        with self._lock:
            detector = self._open()
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self._stamp += 33
            result = detector.detect_for_video(image, self._stamp)

        if not result.hand_landmarks:
            self.gesture = ""
            self._holding, self._held = "", 0
            if self.volume_mode and time.monotonic() - self._volume_at > 0.6:
                self.volume_mode = False  # руку убрали — выходим из режима громкости
            return ""

        marks = list(result.hand_landmarks[0])
        gesture = classify(marks)
        self.gesture = gesture

        if gesture == "ok":
            self._handle_volume(marks)
            return gesture

        self._track(gesture)
        return gesture

    def _track(self, gesture: str) -> None:
        """Жест должен продержаться несколько кадров — иначе это просто взмах рукой."""
        if not gesture:
            self._holding, self._held = "", 0
            return
        if gesture == self._holding:
            self._held += 1
        else:
            self._holding, self._held = gesture, 1
        if self._held != HOLD_FRAMES:
            return

        now = time.monotonic()
        if now - self._cooldown.get(gesture, 0.0) < COOLDOWN_S:
            return
        self._cooldown[gesture] = now
        self.last_fired = gesture
        self._emit(Event(kind=gesture, label=NAMES.get(gesture, gesture)))

    def _handle_volume(self, marks: list[Any]) -> None:
        """Пока держится «окей», расстояние между пальцами задаёт громкость."""
        now = time.monotonic()
        self._volume_at = now
        if not self.volume_mode:
            self.volume_mode = True
            self._emit(Event(kind="ok", label=NAMES["ok"]))
            self._volume_left = now + 0.4  # даём руке устояться перед первым замером
            return
        if now < self._volume_left or now - self._cooldown.get("volume", 0.0) < 0.15:
            return
        self._cooldown["volume"] = now

        # 0.15 ладони — пальцы вместе, 1.1 — разведены; между ними и лежит шкала
        span = (pinch(marks) - 0.15) / (1.10 - 0.15)
        level = int(max(0.0, min(1.0, span)) * 100)
        self._emit(Event(kind="volume", value=level, label=f"громкость {level}"))

    def _emit(self, event: Event) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                pass
