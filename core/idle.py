"""Своя жизнь персонажа в тишине.

Если человека давно не слышно, компаньон изредка подаёт голос сам. Смысл не в
том, чтобы напоминать о себе, а в том, чтобы рядом ощущался кто-то живой.

Поэтому здесь всё построено вокруг сдержанности. Реплика звучит только после
долгой паузы, не чаще одной за большой промежуток, никогда — поверх работы
ассистента, и никогда — дважды подряд одна и та же. Ассистент, который
заговаривает слишком часто, раздражает сильнее молчащего.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Remark:
    """Короткая реплика вместе с тем, как персонаж её подаёт."""

    text: str
    emotion: str = "smile"
    gesture: str = ""


# Наборы растут по мере молчания: сперва лёгкое любопытство, потом откровенная
# скука. Внутри набора реплики равнозначны и выбираются вперемешку.
NUDGE: Final[tuple[Remark, ...]] = (
    Remark("Эй… почему ты застыл?", "doubt", "tilt"),
    Remark("Ты ещё здесь?", "attentive", "tilt"),
    Remark("Чем займёмся?", "happy", "present"),
    Remark("Я тут, если что.", "smile"),
    Remark("Скучно немного.", "sad"),
)

LONG: Final[tuple[Remark, ...]] = (
    Remark("Давно тихо. Всё в порядке?", "doubt", "tilt"),
    Remark("Может, отдохнёшь? Ты уже долго за экраном.", "smile"),
    Remark("Я никуда не денусь. Просто скажи.", "smile", "present"),
    Remark("Если понадоблюсь — я рядом.", "calm"),
)

NIGHT: Final[tuple[Remark, ...]] = (
    Remark("Поздно уже. Может, ко сну?", "sad"),
    Remark("Ночь на дворе, а мы всё работаем.", "smile"),
)

MORNING: Final[tuple[Remark, ...]] = (
    Remark("Доброе утро. С чего начнём?", "happy", "present"),
    Remark("Утро. Кофе и за дело?", "smile"),
)

# по умолчанию: молчит четверть часа, между репликами — не меньше двадцати минут
QUIET_AFTER_S: Final = 15 * 60.0
COOLDOWN_S: Final = 20 * 60.0
# разброс, чтобы реплики не приходили по расписанию
JITTER: Final = 0.45


class IdlePersonality:
    """Решает, стоит ли сейчас подать голос, и какой именно репликой."""

    def __init__(
        self,
        speak: Callable[[str], None],
        react: Callable[[Remark], None] | None = None,
        *,
        enabled: bool = True,
        quiet_after: float = QUIET_AFTER_S,
        cooldown: float = COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
        hour: Callable[[], int] = lambda: time.localtime().tm_hour,
    ) -> None:
        self._speak = speak
        self._react = react
        self.enabled = enabled
        self.quiet_after = quiet_after
        self.cooldown = cooldown
        self._clock = clock
        self._hour = hour

        now = clock()
        self._last_touch = now
        self._last_remark = now      # после запуска молчим полный интервал
        self._recent: list[str] = []
        self._unanswered = 0
        self._threshold = self._next_threshold()

    # ---------------------------------------------------------------- события

    def touch(self) -> None:
        """Человек или ассистент чем-то заняты — отсчёт тишины начинается заново."""
        self._last_touch = self._clock()
        self._unanswered = 0
        self._threshold = self._next_threshold()

    def _next_threshold(self) -> float:
        span = self.quiet_after * JITTER
        return max(30.0, self.quiet_after + random.uniform(-span, span))

    # ---------------------------------------------------------------- решение

    def due(self, busy: bool = False) -> bool:
        """Пора ли говорить. Занятый ассистент — всегда нет."""
        if not self.enabled or busy:
            return False
        now = self._clock()
        # Каждая реплика без ответа удлиняет паузу до следующей. Человек, скорее
        # всего, просто отошёл, и звать его каждые двадцать минут до вечера —
        # худшее, что может делать компаньон.
        pause = self.cooldown * (1 + self._unanswered)
        return (now - self._last_touch >= self._threshold
                and now - self._last_remark >= pause)

    def pool(self) -> Sequence[Remark]:
        """Набор по времени суток и длине паузы."""
        hour = self._hour()
        if hour >= 23 or hour < 5:
            return NIGHT
        quiet = self._clock() - self._last_touch
        if 5 <= hour < 10 and quiet < self.quiet_after * 3:
            return MORNING
        return LONG if quiet >= self.quiet_after * 3 else NUDGE

    def pick(self) -> Remark | None:
        """Реплика, которой давно не было: подряд одно и то же не звучит."""
        options = [item for item in self.pool() if item.text not in self._recent]
        if not options:
            self._recent.clear()
            options = list(self.pool())
        if not options:
            return None
        choice = random.choice(options)
        self._recent.append(choice.text)
        del self._recent[:-4]
        return choice

    def tick(self, busy: bool = False) -> Remark | None:
        """Вызывается по таймеру. Возвращает прозвучавшую реплику или None."""
        if not self.due(busy):
            return None
        remark = self.pick()
        if remark is None:
            return None
        now = self._clock()
        self._last_remark = now
        self._last_touch = now
        self._unanswered += 1
        self._threshold = self._next_threshold()
        if self._react is not None:
            self._react(remark)
        self._speak(remark.text)
        return remark
