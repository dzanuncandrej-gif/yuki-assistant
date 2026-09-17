"""Нейросетевой детектор речи Silero: где начинается и где заканчивается фраза.

Энергетический порог путает речь с хлопком двери, обрывает тихие окончания слов и
запускается на музыке в фоне. Маленькая модель Silero VAD (2 МБ, 0.8 мс на кадр)
отличает голос от шума и делает границы фразы точными — распознавание получает
целые слова, а не обрубки, и ошибается заметно реже.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Any

import numpy as np

FRAME = 512          # столько сэмплов ждёт модель при 16 кГц (32 мс)
SAMPLE_RATE = 16000

_model: Any | None = None
_lock = threading.Lock()


def _model_path() -> Path | None:
    try:
        import silero_vad

        candidate = Path(silero_vad.__file__).resolve().parent / "data" / "silero_vad.jit"
        return candidate if candidate.exists() else None
    except ImportError:
        return None


def available() -> bool:
    return _model_path() is not None


def load() -> Any | None:
    """Модель грузится один раз на процесс. Путь читаем в память: сишный загрузчик
    torch не открывает файлы с кириллицей в пути."""
    global _model
    with _lock:
        if _model is not None:
            return _model
        path = _model_path()
        if path is None:
            return None
        try:
            import torch

            model = torch.jit.load(io.BytesIO(path.read_bytes()), map_location="cpu")
            model.eval()
            torch.set_grad_enabled(False)
            _model = model
        except Exception:  # noqa: BLE001 — без нейросети остаётся энергетический порог
            _model = None
        return _model


class SpeechDetector:
    """Оценивает вероятность речи в блоке звука и сглаживает её по времени."""

    def __init__(self, start_threshold: float = 0.55, end_threshold: float = 0.35) -> None:
        self.start_threshold = float(start_threshold)
        self.end_threshold = float(end_threshold)
        self._model = load()
        self._tail = np.zeros(0, dtype=np.float32)
        self._probability = 0.0

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def probability(self) -> float:
        return self._probability

    def reset(self) -> None:
        self._tail = np.zeros(0, dtype=np.float32)
        self._probability = 0.0
        model = self._model
        if model is not None and hasattr(model, "reset_states"):
            model.reset_states()

    def __call__(self, block: np.ndarray) -> float:
        """Вероятность речи в блоке. Блок любой длины: остаток переносится в следующий вызов."""
        model = self._model
        if model is None:
            return 0.0
        import torch

        data = np.concatenate((self._tail, np.asarray(block, dtype=np.float32)))
        best = 0.0
        offset = 0
        # режим без градиентов включаем на каждый вызов: настройка потоко-локальная,
        # а детектор работает в потоке микрофона
        with torch.no_grad():
            while offset + FRAME <= data.size:
                frame = torch.from_numpy(data[offset : offset + FRAME])
                best = max(best, float(model(frame, SAMPLE_RATE)))
                offset += FRAME
        self._tail = data[offset:]
        # быстрый подъём и медленный спад: конец слова не обрубается на паузе внутри фразы
        self._probability = max(best, self._probability * 0.72)
        return self._probability

    def speaking(self, active: bool) -> bool:
        """Порог с гистерезисом: начать говорить труднее, чем продолжить."""
        threshold = self.end_threshold if active else self.start_threshold
        return self._probability >= threshold
