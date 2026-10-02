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


def _data_dir() -> Path | None:
    """Папка с моделями пакета silero_vad — без его импорта: пакет сам тянет torch."""
    import importlib.util

    spec = importlib.util.find_spec("silero_vad")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations))).resolve() / "data"


def _model_path() -> Path | None:
    folder = _data_dir()
    if folder is None:
        return None
    for name in ("silero_vad.onnx", "silero_vad.jit"):
        candidate = folder / name
        if candidate.exists():
            return candidate
    return None


class _OnnxVad:
    """Silero VAD через onnxruntime — без torch.

    torch ради одного детектора речи держал в памяти около двухсот мегабайт.
    onnxruntime уже есть в процессе (он нужен распознаванию речи), а модель та
    же самая, только в другом формате. Состояние и контекст в 64 сэмпла ведутся
    так же, как в обёртке из пакета silero_vad.
    """

    CONTEXT = 64

    def __init__(self, path: Path) -> None:
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        # путь с кириллицей: модель отдаём байтами, а не именем файла
        self._session = onnxruntime.InferenceSession(path.read_bytes(), sess_options=options,
                                                     providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset_states()

    def reset_states(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def __call__(self, frame: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
        chunk = np.concatenate((self._context, frame.reshape(1, -1).astype(np.float32)), axis=1)
        output, state = self._session.run(None, {"input": chunk, "state": self._state, "sr": self._sr})
        self._state = state
        self._context = chunk[:, -self.CONTEXT:]
        return float(np.asarray(output).reshape(-1)[0])


def available() -> bool:
    return _model_path() is not None


def load() -> Any | None:
    """Модель грузится один раз на процесс. Путь читаем в память: сишный загрузчик
    torch не открывает файлы с кириллицей в пути."""
    global _model
    with _lock:
        if _model is not None:
            return _model
        folder = _data_dir()
        if folder is None:
            return None
        onnx_path = folder / "silero_vad.onnx"
        if onnx_path.exists():
            try:
                _model = _OnnxVad(onnx_path)
                return _model
            except Exception:
                _model = None
        jit_path = folder / "silero_vad.jit"
        if not jit_path.exists():
            return None
        try:
            import torch

            model = torch.jit.load(io.BytesIO(jit_path.read_bytes()), map_location="cpu")
            model.eval()
            torch.set_grad_enabled(False)
            _model = model
        except Exception:
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

        data = np.concatenate((self._tail, np.asarray(block, dtype=np.float32)))
        best = 0.0
        offset = 0
        if isinstance(model, _OnnxVad):
            while offset + FRAME <= data.size:
                best = max(best, model(data[offset : offset + FRAME]))
                offset += FRAME
        else:
            import torch

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
