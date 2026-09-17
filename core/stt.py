"""Локальное распознавание речи на faster-whisper (CTranslate2).

Русский язык задаётся явно, а не угадывается: так реплики из двух слов не уезжают
в сербский или украинский. Перед распознаванием звук выравнивается по громкости —
тихий микрофон был частой причиной «он меня не понимает». Типичные галлюцинации
на тишине («Субтитры сделал…») отбрасываются.

Модель выбирается автоматически: если видеокарта отвечает, берётся крупная и точная,
иначе — быстрая на процессоре. Проверка видеокарты идёт в отдельном потоке с таймаутом,
потому что неисправная связка драйверов умеет зависать намертво.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from . import config, lexicon

LOCAL_MODELS = config.ROOT / "models" / "whisper"

# слова, которые модель должна узнавать уверенно
PROMPT_RU = (
    "Юки. Атлас. Аура. Открой телеграм, запусти хром, сделай скриншот, "
    "громкость тридцать, какие новости, найди в интернете, напиши сообщение, "
    "что видишь на экране, переключись на голос, выключи компьютер, стоп, хватит."
)

# фразы, которые whisper выдумывает на тишине и шуме
_HALLUCINATIONS = re.compile(
    r"^(?:субтитры(?:\s+\w+)*|редактор субтитров.*|корректор.*|продолжение следует.*|"
    r"спасибо за просмотр.*|dimatorzok.*|thanks for watching.*|subscribe.*|"
    r"подписывайтесь на канал.*|請不吝點贊.*|字幕.*|ммм+|ага|угу|э+)$",
    re.IGNORECASE,
)

# целевая громкость перед распознаванием: тихую речь модель слышит хуже
TARGET_RMS = 0.06
_CUDA_PROBE_S = 25.0


def _register_cuda_libraries() -> None:
    """Подкладывает cuDNN и cuBLAS из пакетов nvidia-*: без них CUDA молча не стартует.

    Одного `add_dll_directory` мало. CTranslate2 подтягивает cublas64_12.dll как
    зависимость своей нативной библиотеки, а зависимости ищутся по PATH — каталог,
    добавленный только через add_dll_directory, при этом не просматривается, и
    видеокарта «не заводилась» при полностью установленных пакетах.
    """
    if os.name != "nt":
        return
    site = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "nvidia"
    if not site.exists():
        try:
            import nvidia

            site = Path(nvidia.__file__).resolve().parent
        except ImportError:
            return
    added: list[str] = []
    for folder in sorted(site.glob("*/bin")):
        if not any(folder.glob("*.dll")):
            continue
        added.append(str(folder))
        try:
            os.add_dll_directory(str(folder))
        except (OSError, FileNotFoundError):
            continue
    if added:
        current = os.environ.get("PATH", "")
        missing = [path for path in added if path not in current]
        if missing:
            os.environ["PATH"] = os.pathsep.join([*missing, current])


def normalize_audio(audio: np.ndarray) -> np.ndarray:
    """Выравнивает громкость и убирает постоянную составляющую микрофона."""
    samples = np.asarray(audio, dtype=np.float32)
    if samples.size == 0:
        return samples
    samples = samples - float(np.mean(samples))
    level = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if level < 1e-5:
        return samples
    gain = min(12.0, TARGET_RMS / level)  # тихий микрофон подтягиваем, но не в шум
    boosted = samples * gain
    peak = float(np.max(np.abs(boosted)))
    if peak > 0.98:
        boosted *= 0.98 / peak
    return boosted.astype(np.float32)


class Transcriber:
    """Ленивая обёртка над WhisperModel: модель грузится при первом вызове."""

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self._cfg = dict(cfg)
        self._model: Any | None = None
        self._device = "cpu"
        self._model_name = str(self._cfg.get("model_size", "small"))
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- выбор модели

    def _path(self, size: str) -> str:
        local = LOCAL_MODELS / size
        return str(local) if (local / "model.bin").exists() else size

    def _open(self, size: str, device: str, compute: str) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(
            self._path(size),
            device=device,
            compute_type=compute,
            cpu_threads=int(self._cfg.get("cpu_threads", 0)) or 0,
        )

    def _try_cuda(self, size: str, compute: str) -> Any | None:
        """Пробует поднять модель на видеокарте, но не дольше таймаута.

        Связка драйвер + cuDNN на некоторых машинах зависает без ошибки, поэтому
        ждём в отдельном потоке: не ответила вовремя — работаем на процессоре.
        """
        _register_cuda_libraries()
        box: dict[str, Any] = {}

        def attempt() -> None:
            try:
                box["model"] = self._open(size, "cuda", compute)
            except Exception as err:  # noqa: BLE001
                box["error"] = err

        worker = threading.Thread(target=attempt, name="jarvis-cuda-probe", daemon=True)
        worker.start()
        worker.join(timeout=_CUDA_PROBE_S)
        return box.get("model")

    @property
    def device(self) -> str:
        return self._device

    @property
    def model_name(self) -> str:
        return self._model_name

    def set_language(self, language: str) -> None:
        """Меняет язык распознавания без перезагрузки модели: он читается на каждый вызов."""
        self._cfg["language"] = language

    @property
    def model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model

            requested = str(self._cfg.get("device", "auto")).lower()
            gpu_size = str(self._cfg.get("gpu_model_size", "large-v3-turbo"))
            cpu_size = str(self._cfg.get("model_size", "small"))
            gpu_compute = str(self._cfg.get("gpu_compute_type", "int8_float16"))
            cpu_compute = str(self._cfg.get("compute_type", "int8"))

            # Видеокарта даёт распознавание раз в пять быстрее и точнее: крупная
            # модель на GPU считает фразу за треть секунды там, где маленькая на
            # процессоре тратит полторы. Попытка ограничена таймаутом — на части
            # машин связка драйвер + cuDNN зависает намертво, и тогда молча
            # остаёмся на процессоре, вместо того чтобы ассистент замолчал.
            if requested in ("cuda", "auto") and (LOCAL_MODELS / gpu_size / "model.bin").exists():
                model = self._try_cuda(gpu_size, gpu_compute)
                if model is not None:
                    self._model, self._device, self._model_name = model, "cuda", gpu_size
                    return self._model
                if requested == "cuda":
                    raise RuntimeError("видеокарта не ответила — распознавание останется на процессоре")

            self._model = self._open(cpu_size, "cpu", cpu_compute)
            self._device, self._model_name = "cpu", cpu_size
            return self._model

    # ---------------------------------------------------------------- работа

    def warmup(self) -> None:
        """Прогревает модель тишиной, чтобы первая реальная фраза не ждала загрузки."""
        self.transcribe(np.zeros(16000, dtype=np.float32))

    def transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        """Возвращает (текст, код языка). Аудио — float32 mono 16 кГц."""
        prepared = normalize_audio(audio)
        beam = int(self._cfg.get("beam_size", 0)) or (5 if self._device == "cuda" else 1)

        segments, info = self.model.transcribe(
            prepared,
            language=self._cfg.get("language") or "ru",
            beam_size=beam,
            best_of=beam,
            # границы фразы уже нашёл нейросетевой детектор в core.vad — второй проход не нужен
            vad_filter=bool(self._cfg.get("vad_filter", False)),
            condition_on_previous_text=False,
            initial_prompt=str(self._cfg.get("initial_prompt", "")) or PROMPT_RU,
            temperature=[0.0, 0.2, 0.4],  # если декодирование сорвалось, пробуем мягче
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=float(self._cfg.get("no_speech_threshold", 0.55)),
        )

        pieces: list[str] = []
        for segment in segments:
            piece = segment.text.strip()
            if not piece:
                continue
            if getattr(segment, "no_speech_prob", 0.0) > 0.8:
                continue
            if getattr(segment, "avg_logprob", 0.0) < -1.1:
                continue  # модель сама не уверена — лучше промолчать, чем услышать чушь
            if _HALLUCINATIONS.match(piece.strip(" .!?")):
                continue
            pieces.append(piece)

        text = " ".join(pieces).strip()
        if text and bool(self._cfg.get("lexicon", True)):
            # «Джорвис, открой телеграммы» → «Юки, открой телеграм»
            text = lexicon.correct(text)
        language = getattr(info, "language", "") or ""
        return text, language
