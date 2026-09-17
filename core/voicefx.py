"""Характер и качество голоса: эквалайзер, компрессия, тембр.

Piper выдаёт ровный, слегка глуховатый голос среднего качества. Здесь он доводится до
студийного звучания: убирается гул, снимается «картонная» середина, поднимается
разборчивость и воздух, затем мягкая компрессия выравнивает громкость — речь становится
плотной, живой и одинаково слышной на тихих и громких словах.

Вся обработка векторная (numpy + FFT): кусок в пару секунд считается за единицы
миллисекунд и не мешает потоковому воспроизведению.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

# depth   — сдвиг тона (1.0 без сдвига, меньше — ниже голос)
# bass    — подмешивание низа, грудной резонанс
# mud     — вырез «картонной» середины 250-400 Гц
# presence— подъём разборчивости 3-6 кГц
# air     — воздух выше 8 кГц
# comp    — сила компрессии, 0..1
# drive   — мягкое насыщение (хрипотца)
PRESETS: dict[str, dict[str, float]] = {
    # чистый Piper без обработки — на случай сравнения
    "raw": {"depth": 1.0, "bass": 0.0, "mud": 0.0, "presence": 0.0, "air": 0.0, "comp": 0.0, "drive": 0.0},
    # живой и разборчивый: студийная доводка без смены тембра
    "natural": {"depth": 1.0, "bass": 0.06, "mud": 0.22, "presence": 0.34, "air": 0.22, "comp": 0.55, "drive": 0.0},
    # тёплый мужской: чуть ниже и плотнее
    "deep": {"depth": 0.985, "bass": 0.16, "mud": 0.26, "presence": 0.30, "air": 0.18, "comp": 0.6, "drive": 0.02},
    # кинематографичный Юки: низ, металл в согласных, ровная громкость
    "cinema": {"depth": 0.975, "bass": 0.22, "mud": 0.3, "presence": 0.38, "air": 0.26, "comp": 0.7, "drive": 0.04},
    # прежний «стальной» вариант, оставлен для совместимости с конфигами
    "hard": {"depth": 0.97, "bass": 0.26, "mud": 0.3, "presence": 0.32, "air": 0.2, "comp": 0.65, "drive": 0.06},
    # женский аниме-тембр. Тон не трогаем: голоса Irina и Xenia женские сами по
    # себе, а сдвиг пересэмплированием делал из них «бурундука» — он поднимает
    # вместе с тоном и форманты, ускоряет речь и рвёт стык между кусками потока.
    # Характер даётся эквалайзером: убранный низ, вырезанная середина, воздух.
    "anime": {"depth": 1.0, "bass": 0.0, "mud": 0.34, "presence": 0.32, "air": 0.42, "comp": 0.45, "drive": 0.0},
    # тот же характер, но спокойнее: для длинных ответов
    "anime_soft": {"depth": 1.0, "bass": 0.02, "mud": 0.28, "presence": 0.26, "air": 0.34, "comp": 0.5, "drive": 0.0},
    # Самурай: низкий, плотный, властный — но разборчивый.
    #
    # `depth` намеренно единица, то есть тон не трогается пересэмплированием.
    # Именно оно даёт то самое «ведро» и щелчки на стыках кусков потока: вместе с
    # тоном уезжают форманты и меняется длительность. Глубину даёт синтез — Edge
    # умеет опускать тон на своей стороне чисто, без артефактов.
    #
    # Здесь тембр лепится только эквалайзером: поднят низ, слегка убрана муть,
    # заметно поднято присутствие ради чёткости согласных, срезан воздух (шипящие
    # в низком мужском голосе звучат сибилянтно), сильная компрессия — ровная
    # громкость читается как спокойная уверенность.
    # Ниндзя: уверенный, но не давящий. Прежний вариант был перекачан низом и
    # пережат — голос выходил «в бочке» и утомлял. Низ убавлен, воздух возвращён
    # (без него согласные глухие и звучит как из подвала), компрессия ослаблена —
    # живая динамика читается как спокойствие, а не как напор.
    "samurai": {"depth": 1.0, "bass": 0.20, "mud": 0.16, "presence": 0.38, "air": 0.22, "comp": 0.58, "drive": 0.0},
}

DEFAULT_PRESET = "cinema"

# целевая громкость речи: RMS около -19 dBFS звучит ровно и не режет уши
TARGET_RMS = 0.11

# насколько полно выравнивать громкость куска: 1.0 — точно в цель и без
# интонации, 0.0 — не трогать вовсе
_LEVELLING = 0.62


def settings(preset: str) -> dict[str, float]:
    return dict(PRESETS.get(preset, PRESETS[DEFAULT_PRESET]))


def preset_names() -> tuple[str, ...]:
    return tuple(PRESETS)


# ---------------------------------------------------------------- элементы обработки


def _pitch_down(samples: np.ndarray, factor: float) -> np.ndarray:
    """Сдвигает тон пересэмплированием.

    factor < 1 — сигнал растягивается, голос звучит ниже и крупнее.
    factor > 1 — сжимается, голос становится выше и легче: так делается женский
    аниме-тембр поверх нейтрального синтеза.
    """
    if samples.size == 0 or 0.999 <= factor <= 1.001:
        return samples
    length = max(8, int(len(samples) / factor))
    positions = np.linspace(0.0, len(samples) - 1, length)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)


def _equalize(
    samples: np.ndarray,
    rate: int,
    bass: float,
    mud: float,
    presence: float,
    air: float,
) -> np.ndarray:
    """Одна свёртка в частотной области: рокот вниз, середина вырезана, верх поднят.

    Всё сделано одним проходом FFT — четыре отдельных фильтра стоили бы вчетверо дороже.
    """
    if samples.size < 64:
        return samples
    if bass <= 0 and mud <= 0 and presence <= 0 and air <= 0:
        return samples

    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / rate)
    response = np.ones_like(freqs)

    # обрезной снизу: гул микрофонной комнаты и подрагивание синтеза
    response *= freqs / np.sqrt(freqs**2 + 68.0**2)

    if bass > 0:  # грудной резонанс
        response += bass * np.exp(-(((freqs - 120.0) / 90.0) ** 2))
    if mud > 0:  # «картон» середины — вырез
        response -= mud * np.exp(-(((freqs - 320.0) / 190.0) ** 2))
    if presence > 0:  # разборчивость согласных
        response += presence * np.exp(-(((freqs - 4200.0) / 2200.0) ** 2))
    if air > 0:  # воздух и «дыхание» голоса
        response += air * (1.0 / (1.0 + np.exp(-(freqs - 8500.0) / 1800.0)))

    response = np.clip(response, 0.05, 3.0)
    return np.fft.irfft(spectrum * response, n=samples.size).astype(np.float32)


def _moving_rms(samples: np.ndarray, window: int) -> np.ndarray:
    """Скользящее среднеквадратичное через кумулятивную сумму — без циклов Python."""
    window = max(8, int(window))
    padded = np.pad(samples.astype(np.float64) ** 2, (window // 2, window // 2), mode="edge")
    cumulative = np.cumsum(padded)
    sums = cumulative[window:] - cumulative[:-window]
    envelope = np.sqrt(np.maximum(sums / window, 1e-12))
    return envelope[: samples.size].astype(np.float32)


def _compress(samples: np.ndarray, rate: int, amount: float) -> np.ndarray:
    """Мягкая компрессия: тихие слоги подтягиваются, громкие не бьют по ушам.

    Огибающая и сглаживание усиления считаются свёрткой, поэтому обработка остаётся
    векторной: атака слышится мягкой, а отпускание — естественным.
    """
    if amount <= 0.0 or samples.size < 256:
        return samples

    ratio = 1.0 + 5.0 * float(np.clip(amount, 0.0, 1.0))  # до 6:1
    threshold = 0.035  # примерно -29 dBFS: работаем со средним уровнем речи

    envelope = _moving_rms(samples, int(rate * 0.012))
    over = np.maximum(envelope, 1e-6) / threshold
    gain = np.where(over > 1.0, over ** (1.0 / ratio - 1.0), 1.0).astype(np.float32)

    # сглаживание усиления ≈ атака 8 мс / отпускание 90 мс
    window = max(8, int(rate * 0.03))
    kernel = np.hanning(window)
    kernel /= kernel.sum()
    smooth = np.convolve(gain, kernel, mode="same").astype(np.float32)
    return (samples * smooth).astype(np.float32)


def _drive(samples: np.ndarray, amount: float) -> np.ndarray:
    """Мягкое насыщение: добавляет хрипотцы, не превращая речь в перегруз."""
    if amount <= 0.0:
        return samples
    k = 1.0 + amount * 4.0
    return (np.tanh(samples * k) / np.tanh(k)).astype(np.float32)


def _normalize(samples: np.ndarray, gain: float) -> np.ndarray:
    """Подтягивает громкость к целевой и мягко ограничивает пики.

    Коррекция намеренно неполная. Речь синтезируется кусками, и если каждый
    кусок выравнивать точно в одну громкость, тихая концовка фразы звучит так же
    напористо, как ударное начало: интонация пропадает, а на стыках слышны
    ступеньки уровня. Частичная поправка оставляет живую динамику.
    """
    if samples.size == 0:
        return samples
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms < 1e-6:
        return samples
    ratio = min(2.2, max(0.5, (TARGET_RMS / rms) ** _LEVELLING))
    scaled = samples * ratio * max(0.1, float(gain))
    peak = float(np.max(np.abs(scaled)))
    if peak > 0.95:  # мягкий лимитер вместо жёсткого клиппинга
        scaled = np.tanh(scaled / peak * 1.1) * 0.95
    return scaled.astype(np.float32)


# ---------------------------------------------------------------- основной вход


def shape(
    samples: np.ndarray,
    rate: int,
    depth: float = 0.975,
    bass: float = 0.22,
    drive: float = 0.04,
    gain: float = 1.0,
    mud: float = 0.3,
    presence: float = 0.38,
    air: float = 0.26,
    comp: float = 0.7,
) -> np.ndarray:
    """Обрабатывает кусок речи (float32 mono, -1..1) и возвращает новый массив.

    Порядок как на студийном тракте: тон → эквалайзер → компрессия → насыщение →
    нормализация. Сильный сдвиг тона (depth ниже 0.95) смазывает согласные, поэтому
    в пресетах он держится в пределах пары процентов.
    """
    if samples.size == 0:
        return samples

    processed = np.asarray(samples, dtype=np.float32)
    processed = _pitch_down(processed, depth)
    processed = _equalize(processed, rate, bass, mud, presence, air)
    processed = _compress(processed, rate, comp)
    processed = _drive(processed, drive)
    return _normalize(processed, gain)


# ---------------------------------------------------------------- работа с файлами


def _read(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError("ожидался 16-битный WAV")
        channels = source.getnchannels()
        rate = source.getframerate()
        raw = source.readframes(source.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def _write(path: Path, samples: np.ndarray, rate: int) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes((clipped * 32767.0).astype(np.int16).tobytes())


def process(path: Path, **kwargs: float) -> Path:
    """Обрабатывает WAV на месте — для движков, которые умеют только файлы."""
    samples, rate = _read(path)
    if samples.size == 0:
        return path
    _write(path, shape(samples, rate, **kwargs), rate)
    return path
