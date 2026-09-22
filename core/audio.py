"""Звук: захват микрофона с энергетическим VAD и потоковое воспроизведение речи.

Микрофон отдаёт готовые реплики (float32 mono). Player принимает куски синтеза и пишет
их в звуковую карту небольшими блоками, поэтому речь обрывается мгновенно по команде.
"""

from __future__ import annotations

import queue
import threading
import wave
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

from . import lipsync, vad

LevelCallback = Callable[[float], None]
VisemeCallback = Callable[[dict[str, float]], None]
StopCheck = Callable[[], bool]

_LEVEL_GAIN = 6.0  # RMS речи ~0.05..0.15 → нормируем к 0..1 для шейдера


def resolve_device(value: int | str | None, kind: str) -> int | str | None:
    """Если устройство не задано, берём системный маппер Windows — он следует за
    устройством по умолчанию, а не за первым попавшимся виртуальным драйвером."""
    if value is not None:
        return value
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for index, device in enumerate(devices):
        name = str(device["name"]).lower()
        if device[key] > 0 and ("mapper" in name or "переназначение" in name):
            return index
    return None


# ниже этого уровня устройство считается мёртвым: живой микрофон даже в тишине
# отдаёт собственный шум порядка 0.0003
SILENT_LEVEL = 8e-5

# виртуальные и служебные устройства, которые не стоит выбирать самостоятельно
_SKIP_INPUT = ("steam streaming", "стерео микшер", "stereo mix", "virtual", "voicemeeter", "cable")


def probe_input(device: int | str | None, seconds: float = 0.35, rate: int = 16000) -> float:
    """Средняя громкость устройства за короткую запись. 0.0 — устройство молчит."""
    try:
        recording = sd.rec(
            int(max(0.1, seconds) * rate), samplerate=rate, channels=1, dtype="float32",
            device=device, blocking=True,
        )
    except Exception:
        return -1.0
    return rms(recording[:, 0])


def working_input(preferred: int | str | None = None, seconds: float = 0.35) -> tuple[int | str | None, str]:
    """Выбирает микрофон, который реально что-то слышит.

    Windows нередко оставляет устройством по умолчанию отключённый или заглушённый
    микрофон: он исправно открывается и отдаёт ровную цифровую тишину. Ассистент при
    этом выглядит сломанным — «не слышит». Поэтому перед стартом устройства
    прослушиваются, и берётся то, где есть сигнал.
    """
    if preferred is not None:
        level = probe_input(preferred, seconds)
        if level > SILENT_LEVEL:
            return preferred, f"{_device_name(preferred)} (уровень {level:.4f})"
        # заданное устройство молчит — ищем живое, но выбор пользователя не забываем
    try:
        devices = sd.query_devices()
    except Exception:
        return preferred, "список устройств недоступен"

    scored: list[tuple[float, int, str]] = []
    for index, device in enumerate(devices):
        if device["max_input_channels"] <= 0:
            continue
        api = str(sd.query_hostapis(device["hostapi"])["name"]).lower()
        if "wasapi" in api or "wdm" in api:
            continue  # эти интерфейсы на Windows часто отказываются открывать 16 кГц
        name = str(device["name"])
        if any(mark in name.lower() for mark in _SKIP_INPUT):
            continue
        level = probe_input(index, seconds)
        if level > SILENT_LEVEL:
            scored.append((level, index, name))

    if not scored:
        return preferred, "ни одно устройство не даёт сигнала — проверь, не выключен ли микрофон"
    scored.sort(reverse=True)
    level, index, name = scored[0]
    return index, f"{name} (уровень {level:.4f})"


def _device_name(device: int | str | None) -> str:
    try:
        info = sd.query_devices(device)
        return str(info["name"])
    except Exception:
        return str(device)


def rms(chunk: np.ndarray) -> float:
    if chunk.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))


def to_level(value: float) -> float:
    scaled = value * _LEVEL_GAIN
    return 1.0 if scaled > 1.0 else scaled


# ---------------------------------------------------------------- воспроизведение


class Player:
    """Открытый поток вывода: куски пишутся по мере синтеза, без файлов и пауз.

    Поток переиспользуется между репликами: открытие устройства стоит десятки
    миллисекунд и на некоторых картах щёлкает, если делать это на каждую фразу.
    """

    _shared: Player | None = None
    _shared_lock = threading.Lock()

    def __init__(self, sample_rate: int, device: int | str | None = None, block_ms: int = 40) -> None:
        self.sample_rate = int(sample_rate)
        self.device = resolve_device(device, "output")
        self.block = max(256, int(self.sample_rate * block_ms / 1000))
        self._stream: sd.OutputStream | None = None
        # разбор рта создаётся при первой речи: без него поток вывода не нужен
        self._analyser: lipsync.VisemeAnalyser | None = None

    @classmethod
    def shared(cls, sample_rate: int, device: int | str | None = None) -> Player:
        """Один поток вывода на приложение. Частота сменилась — пересоздаём."""
        with cls._shared_lock:
            player = cls._shared
            if player is not None and player.sample_rate == int(sample_rate) and player.alive:
                return player
            if player is not None:
                player.close()
            player = cls(sample_rate, device)
            player.open()
            cls._shared = player
            return player

    @classmethod
    def release_shared(cls) -> None:
        with cls._shared_lock:
            if cls._shared is not None:
                cls._shared.close()
                cls._shared = None

    @property
    def alive(self) -> bool:
        stream = self._stream
        return stream is not None and stream.active

    def open(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            blocksize=self.block,
            latency="low",
        )
        self._stream.start()

    def write(
        self,
        samples: np.ndarray,
        should_stop: StopCheck | None = None,
        on_level: LevelCallback | None = None,
        on_viseme: VisemeCallback | None = None,
    ) -> bool:
        """Пишет кусок блоками. False — воспроизведение прервано.

        Тот же блок, что уходит в звуковую карту, разбирается на положение рта:
        губы аватара двигаются по тому самому звуку, который слышит человек.
        """
        if self._stream is None:
            self.open()
        stream = self._stream
        if stream is None:
            return False
        if on_viseme is not None and self._analyser is None:
            self._analyser = lipsync.VisemeAnalyser(self.sample_rate)
        data = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        for start in range(0, data.size, self.block):
            if should_stop is not None and should_stop():
                return False
            block = data[start : start + self.block]
            stream.write(block)
            # мимика — украшение, речь — нет: сбой в разборе рта не должен
            # обрывать звук. Но и молчать о нём нельзя — иначе губы «просто
            # перестают работать», и причину потом не найти
            try:
                if on_level is not None:
                    on_level(to_level(rms(block)))
                if on_viseme is not None and self._analyser is not None:
                    on_viseme(self._analyser(block))
            except Exception as err:
                from . import bus

                bus.bus.log("error", f"Мимика отключена до конца реплики: {err!r}")
                on_level = None
                on_viseme = None
        return True

    def flush(self) -> None:
        """Сбрасывает недоигранный звук, оставляя поток открытым."""
        stream = self._stream
        if stream is None:
            return
        try:
            stream.abort()
            stream.start()
        except Exception:
            self.close()

    def close(self, drain: bool = True) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            if not drain:
                stream.abort()
            stream.stop()
        finally:
            stream.close()


def play_wav(
    path: Path,
    on_level: LevelCallback | None = None,
    device: int | str | None = None,
    should_stop: StopCheck | None = None,
) -> None:
    """Проигрывает готовый WAV — используется для сигналов и отладки."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError("ожидался 16-битный WAV")
        channels = handle.getnchannels()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    player = Player(rate, device=device)
    player.open()
    try:
        player.write(samples, should_stop=should_stop, on_level=on_level)
    finally:
        player.close()
    if on_level is not None:
        on_level(0.0)


# ---------------------------------------------------------------- захват


class Microphone:
    """Слушает микрофон и отдаёт готовые реплики (float32 mono, sample_rate)."""

    def __init__(self, cfg: Mapping[str, Any], on_level: LevelCallback | None = None) -> None:
        self.sample_rate = int(cfg["sample_rate"])
        self.block_size = int(self.sample_rate * int(cfg["block_ms"]) / 1000)
        self.silence_blocks = max(1, int(cfg["silence_ms"] / cfg["block_ms"]))
        self.min_speech_blocks = max(1, int(cfg["min_speech_ms"] / cfg["block_ms"]))
        self.max_blocks = max(1, int(cfg["max_utterance_ms"] / cfg["block_ms"]))
        self.calibration_blocks = max(1, int(cfg["calibration_ms"] / cfg["block_ms"]))
        self.threshold_scale = float(cfg["vad_threshold_scale"])
        self.threshold_floor = float(cfg["vad_threshold_floor"])
        # во время речи ассистента порог поднимается: иначе он слышит сам себя
        self.barge_in_scale = float(cfg.get("barge_in_scale", 3.5))
        self.barge_in_blocks = max(1, int(cfg.get("barge_in_ms", 260) / cfg["block_ms"]))
        self.device = resolve_device(cfg.get("input_device"), "input")
        self.device_note = ""
        if bool(cfg.get("auto_input", True)):
            chosen, note = working_input(cfg.get("input_device"))
            self.device, self.device_note = chosen, note
        self.on_level = on_level
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._threshold = self.threshold_floor
        self._loud_while_muted = 0
        self._lock = threading.Lock()

        # запас звука до начала речи: без него теряется первый слог
        preroll_blocks = max(1, int(cfg.get("preroll_ms", 320) / cfg["block_ms"]))
        self._preroll: deque[np.ndarray] = deque(maxlen=preroll_blocks)

        self._detector: vad.SpeechDetector | None = None
        if bool(cfg.get("neural_vad", True)):
            detector = vad.SpeechDetector(
                start_threshold=float(cfg.get("vad_start", 0.55)),
                end_threshold=float(cfg.get("vad_end", 0.35)),
            )
            self._detector = detector if detector.ready else None

    @property
    def detector_name(self) -> str:
        return "нейросетевой Silero" if self._detector is not None else "энергетический порог"

    # --- внутреннее ---

    def _callback(self, indata, frames, time_info, status) -> None:
        self._queue.put(indata[:, 0].copy())

    def _calibrate(self) -> float:
        samples = []
        for _ in range(self.calibration_blocks):
            samples.append(rms(self._queue.get()))
        noise = float(np.median(samples)) if samples else 0.0
        return max(self.threshold_floor, noise * self.threshold_scale)

    @property
    def threshold(self) -> float:
        return self._threshold

    # --- публичное API ---

    def utterances(
        self,
        should_stop: Callable[[], bool],
        gate: Callable[[], bool] | None = None,
        on_barge_in: Callable[[], None] | None = None,
    ) -> Iterator[np.ndarray]:
        """Бесконечный генератор реплик.

        `gate` возвращает False, когда слушать нельзя (ассистент говорит). В это время
        блоки не копятся, но громкий звук сверх повышенного порога считается перебиванием
        и вызывает `on_barge_in` — так работает команда «Юки, хватит».
        """
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        with stream:
            self._threshold = self._calibrate()
            buffer: list[np.ndarray] = []
            silence_run = 0
            speaking = False

            while not should_stop():
                try:
                    block = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if gate is not None and not gate():
                    buffer, silence_run, speaking = [], 0, False
                    # Пока ассистент говорит, звук копится в предзаписи, а не
                    # выбрасывается. Иначе начало перебивающей фразы терялось:
                    # человек говорил «Юки, хватит», она замолкала — и слышала
                    # только «хватит», потеряв обращение.
                    self._preroll.append(block)
                    if on_barge_in is not None and self._is_barge_in(block):
                        self._loud_while_muted += 1
                        if self._loud_while_muted >= self.barge_in_blocks:
                            self._loud_while_muted = 0
                            if self._detector is not None:
                                self._detector.reset()
                            on_barge_in()
                    elif self._loud_while_muted:
                        self._loud_while_muted = max(0, self._loud_while_muted - 1)
                    continue
                self._loud_while_muted = 0

                energy = rms(block)
                voice = self._is_voice(block, energy, speaking)

                if self.on_level is not None:
                    self.on_level(to_level(energy) if voice or speaking else 0.0)

                if voice:
                    if not speaking:
                        # добираем звук, записанный до срабатывания: первое слово
                        # начинается раньше, чем детектор успевает его признать
                        buffer.extend(self._preroll)
                        self._preroll.clear()
                    speaking = True
                    silence_run = 0
                    buffer.append(block)
                elif speaking:
                    silence_run += 1
                    buffer.append(block)
                    if silence_run >= self.silence_blocks:
                        payload = self._finish(buffer)
                        buffer, silence_run, speaking = [], 0, False
                        if self._detector is not None:
                            self._detector.reset()
                        if payload is not None:
                            yield payload
                else:
                    self._preroll.append(block)
                    # тишина — медленно подстраиваем порог под фоновый шум
                    self._threshold = max(
                        self.threshold_floor,
                        0.95 * self._threshold + 0.05 * energy * self.threshold_scale,
                    )

                if speaking and len(buffer) >= self.max_blocks:
                    payload = self._finish(buffer)
                    buffer, silence_run, speaking = [], 0, False
                    if payload is not None:
                        yield payload

    def _is_barge_in(self, block: np.ndarray) -> bool:
        """Перебивают ли ассистента.

        Раньше решала одна громкость — и музыка или видео из колонок обрывали ответ
        на полуслове. Теперь громкий звук должен быть ещё и распознан как речь.
        """
        if rms(block) <= self._threshold * self.barge_in_scale:
            return False
        detector = self._detector
        if detector is None or not detector.ready:
            return True
        return detector(block) >= max(0.75, detector.start_threshold + 0.2)

    def _is_voice(self, block: np.ndarray, energy: float, speaking: bool) -> bool:
        """Речь это или шум. Нейросеть точнее порога, но порог остаётся страховкой."""
        detector = self._detector
        if detector is not None and detector.ready:
            detector(block)
            # совсем тихие блоки не считаем речью, даже если сеть сомневается
            return detector.speaking(speaking) and energy > self.threshold_floor * 0.5
        return energy > self._threshold

    def _finish(self, buffer: list[np.ndarray]) -> np.ndarray | None:
        voiced = len(buffer) - self.silence_blocks
        if voiced < self.min_speech_blocks:
            return None
        if self.on_level is not None:
            self.on_level(0.0)
        payload = np.concatenate(buffer)
        # хвост тишины моделью не нужен, а вот 150 мс запаса помогают не срезать слово
        keep = int(self.sample_rate * 0.15)
        extra = (self.silence_blocks * self.block_size) - keep
        return payload[:-extra] if extra > 0 and payload.size > extra * 2 else payload

    def drain(self) -> None:
        """Сбрасывает накопленный звук — вызывается после того, как ассистент отговорил."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


def list_devices() -> str:
    return str(sd.query_devices())
