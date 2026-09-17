"""Разбор звука речи на положения рта.

Ассистент говорит синтезом, фонем на выходе нет — есть только волна. Но форма
рта на гласных различается прежде всего распределением энергии по спектру:
у «у» вся сила внизу, у «и» — наверху, «а» шире всех остальных. Поэтому блок
звука раскладывается на пять полос и сравнивается с эталонами гласных.

Точность здесь не фонетическая, а зрительная: важно, чтобы губы двигались в
такт голосу и меняли форму, а не открывались и закрывались одинаково. Этого
такой оценки хватает, и стоит она сотые доли миллисекунды на блок.
"""

from __future__ import annotations

from typing import Final

import numpy as np

# границы полос в герцах: первая форманта разбита мелко (у «у» она около 300,
# у «о» — 500, у «а» — 700, и путать их нельзя), вторая — крупнее
_EDGES: Final = (170.0, 400.0, 640.0, 950.0, 1450.0, 2100.0, 3000.0, 4200.0)

# эталоны: насколько громкой должна быть каждая полоса для данной гласной.
# Значения подобраны по спектру речи самого синтезатора, уже с предыскажением.
_TEMPLATES: Final = {
    "a": np.array([0.28, 0.62, 0.95, 0.90, 0.48, 0.22, 0.12], dtype=np.float32),
    "o": np.array([0.52, 0.95, 0.72, 0.34, 0.16, 0.10, 0.08], dtype=np.float32),
    "u": np.array([0.95, 0.62, 0.55, 0.16, 0.09, 0.07, 0.05], dtype=np.float32),
    "e": np.array([0.30, 0.72, 0.58, 0.62, 0.95, 0.46, 0.20], dtype=np.float32),
    "i": np.array([0.62, 0.40, 0.22, 0.26, 0.55, 1.00, 0.58], dtype=np.float32),
}

# предыскажение: речь завалена вниз примерно на 6 дБ на октаву, и без подъёма
# верхов первая полоса перекрикивает все остальные, а разница гласных теряется
_PREEMPHASIS: Final = 0.97
_ORDER: Final = ("a", "e", "i", "o", "u")
_MATRIX: Final = np.stack([_TEMPLATES[key] for key in _ORDER])
_MATRIX_UNIT: Final = _MATRIX / np.linalg.norm(_MATRIX, axis=1, keepdims=True)

_SHARPNESS: Final = 5.0     # степень, которой подчёркивается ближайшая гласная
_OPEN_GAIN: Final = 7.5     # RMS речи мал, рот должен открываться заметно
_SILENCE: Final = 6e-4

# частота смены знака, выше которой звук — шипящий согласный, а не гласный.
# Различать их по спектру нельзя: у «с» и у «и» энергия одинаково наверху,
# но гласная периодична, а шум знак меняет вдвое чаще
# Порог измерен на самом синтезаторе: у гласных 90-й процентиль 0.08, у «с/ш/ч»
# медиана 0.18. Между ними и проходит граница.
_ZCR_MAX: Final = 0.12
# насколько прикрыт рот на согласном
_CONSONANT_OPEN: Final = 0.42


class VisemeAnalyser:
    """Превращает блоки звука в веса гласных. Один экземпляр на поток вывода."""

    def __init__(self, sample_rate: int, smoothing: float = 0.35) -> None:
        self.sample_rate = int(sample_rate)
        self.smoothing = float(smoothing)
        self._size = 0
        self._window: np.ndarray | None = None
        self._slices: tuple[slice, ...] = ()
        self._state = np.zeros(len(_ORDER), dtype=np.float32)
        self._open = 0.0

    def _prepare(self, size: int) -> None:
        """Окно и границы полос зависят только от длины блока — считаем их раз."""
        self._size = size
        self._window = np.hanning(size).astype(np.float32)
        freqs = np.fft.rfftfreq(size, 1.0 / self.sample_rate)
        self._slices = tuple(
            slice(int(np.searchsorted(freqs, low)), int(np.searchsorted(freqs, high)))
            for low, high in zip(_EDGES, _EDGES[1:])
        )

    def reset(self) -> None:
        self._state[:] = 0.0
        self._open = 0.0

    def __call__(self, block: np.ndarray) -> dict[str, float]:
        samples = np.asarray(block, dtype=np.float32).ravel()
        if samples.size < 64:
            return self._result(0.0)

        level = float(np.sqrt(np.mean(np.square(samples))))
        if level < _SILENCE:
            return self._result(0.0)

        if samples.size != self._size:
            self._prepare(samples.size)

        zcr = np.count_nonzero(np.diff(np.signbit(samples))) / max(1, samples.size - 1)

        shaped = np.empty_like(samples)
        shaped[0] = samples[0]
        np.subtract(samples[1:], samples[:-1] * _PREEMPHASIS, out=shaped[1:])
        spectrum = np.abs(np.fft.rfft(shaped * self._window))
        bands = np.array([float(spectrum[part].sum()) for part in self._slices], dtype=np.float32)
        total = float(bands.sum())
        if total <= 1e-9:
            return self._result(0.0)

        # Согласные — не гласные. У «с», «ш», «ч» вся энергия наверху, и по
        # формантам они неотличимы от «и»: без этой проверки рот на русской речи
        # почти всё время стоял в улыбке. Шипящий звук рот прикрывает и форму
        # оставляет прежней, а не дёргает её на каждый свист.
        if zcr > _ZCR_MAX:
            return self._result(min(1.0, level * _OPEN_GAIN) * _CONSONANT_OPEN)

        # сравнение по направлению, а не по громкости: тихая «и» остаётся «и»
        unit = bands / np.linalg.norm(bands)
        scores = np.clip(_MATRIX_UNIT @ unit, 0.0, None) ** _SHARPNESS
        weights = scores / max(float(scores.sum()), 1e-9)

        self._state += (weights - self._state) * (1.0 - self.smoothing)
        return self._result(min(1.0, level * _OPEN_GAIN))

    def _result(self, openness: float) -> dict[str, float]:
        # закрывается рот быстрее, чем открывается: иначе речь выглядит вялой
        rate = 0.55 if openness > self._open else 0.35
        self._open += (openness - self._open) * rate
        if openness <= 0.0 and self._open < 0.01:
            self._state *= 0.6
        out = {"open": round(float(self._open), 4)}
        for index, key in enumerate(_ORDER):
            out[key] = round(float(self._state[index]), 4)
        return out
