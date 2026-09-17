"""Дискретно-событийная симуляция предприятия.

Событийная модель, а не пошаговая. Разница принципиальна: шаг по времени
заставляет выбирать между точностью и скоростью — мелкий шаг считает вечность,
крупный теряет очереди, — тогда как события считаются только там, где что-то
происходит. Год работы завода на двести сорок человек укладывается здесь в доли
секунды, и это не оптимизация ради оптимизации: ползунок сценария должен
отзываться при человеке, иначе разговор с двойником разваливается на ожидание.

Симуляция детерминирована при заданном зерне. Директор, задавший один и тот же
вопрос дважды, обязан получить один и тот же ответ — иначе он перестанет верить
любому числу отсюда, и правильно сделает.
"""

from __future__ import annotations

import heapq
import math
import random as _random
from array import array
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .model import SHIFT_MINUTES, WORK_DAYS_MONTH, Plant

# Разогрев: первые дни предприятие стоит пустым, очереди только набираются, и
# среднее по ним занижает и срок, и потери. Этот отрезок считается, но в
# статистику не идёт.
WARMUP_DAYS = 15

# Сколько операций может выпасть на один заказ: все переделы плюс запас на
# повторные проходы по петлям брака. Запас щедрый нарочно — заказ, у которого
# кончились заготовленные числа, пошёл бы по кругу чужих, и общие случайные
# числа перестали бы быть общими.
_SLOTS_SPARE = 26

_DRAWS: dict[tuple, tuple[array, array]] = {}


def _draws(seed: int, jobs: int, slots: int) -> tuple[array, array]:
    """Заготовленные случайные числа: по строке на заказ.

    Это условие сравнимости сценариев, а не приём ускорения. При общем потоке
    случайных чисел добавленный человек меняет порядок событий, порядок меняет,
    кому какое число достанется, — и два прогона расходятся не только из-за
    самого изменения, но и из-за перетасовки случайности. Разница сценариев
    тонет в этом шуме: участок, загруженный на две трети, начинает показывать
    выигрыш наравне с настоящим ограничением, и рекомендация становится ложью.

    Строка на заказ убирает шум полностью. Заказ получает одни и те же
    длительности операций и одни и те же жребии на брак в любом сценарии, потому
    что они зависят только от него самого, а не от очередей вокруг.

    Числа лежат плоскими массивами `array`, а не двумерными numpy. Обращение к
    одиночному элементу numpy создаёт объект-скаляр и стоит втрое дороже родного
    списка, а обращений здесь под миллион на прогон — на такой частоте разница
    между двумястами и шестьюдесятью наносекундами решает, отзовётся ползунок
    сценария при человеке или нет.
    """
    key = (seed, jobs, slots)
    found = _DRAWS.get(key)
    if found is not None:
        return found
    generator = np.random.default_rng(seed)
    normals, uniforms = array("f"), array("f")
    normals.frombytes(generator.standard_normal(jobs * slots, dtype=np.float32).tobytes())
    uniforms.frombytes(generator.random(jobs * slots, dtype=np.float32).tobytes())
    # Набор нужен ровно один: он общий для всех сценариев одного предприятия.
    _DRAWS.clear()
    _DRAWS[key] = (normals, uniforms)
    return normals, uniforms


@dataclass
class StationStat:
    """Что участок накопил за прогон."""

    id: str
    name: str
    staff: int
    served: int = 0
    reworked: int = 0
    busy_minutes: float = 0.0
    wait_minutes: float = 0.0
    queue_area: float = 0.0      # интеграл длины очереди по времени
    queue_peak: int = 0
    queue_end: int = 0
    by_month_busy: list = field(default_factory=list)
    by_month_area: list = field(default_factory=list)

    def summary(self, minutes: float, days: float) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "staff": self.staff,
            "served": self.served,
            "reworked": self.reworked,
            # Загрузка — доля занятого времени от всего доступного времени всех
            # людей участка, а не от одного человека.
            "load": self.busy_minutes / max(minutes * self.staff, 1.0),
            "queue_avg": self.queue_area / max(minutes, 1.0),
            "queue_peak": self.queue_peak,
            "queue_end": self.queue_end,
            "wait_days": (self.wait_minutes / max(self.served, 1)) / SHIFT_MINUTES,
            "throughput_day": self.served / max(days, 1.0),
        }


@dataclass
class _Station:
    """Рабочее состояние участка во время прогона."""

    id: str
    name: str
    servers: int
    minutes: float
    spread: float
    defect: float
    rework_to: str | None
    mu: float = 0.0
    sigma: float = 0.0
    # Куда возвращать брак — позицией в маршруте, а не именем. Поиск по имени в
    # словаре на каждом событии обходится дороже самой операции, а событий
    # порядка миллиона на прогон.
    rework_index: int = -1
    free: int = 0
    # Двусторонняя очередь, а не список. Перед узким местом копятся тысячи
    # заказов, и забор из головы обычного списка сдвигает весь его хвост: на
    # очереди в две тысячи это две тысячи перемещений указателей на каждую
    # завершённую операцию. Ровно та ошибка, которая не видна на игрушечной
    # модели и утраивает время прогона на настоящей.
    queue: deque = field(default_factory=deque)
    stat: StationStat = None  # type: ignore[assignment]
    _marked: float = 0.0

    def touch(self, now: float, month: int) -> None:
        """Копит интеграл очереди. Вызывается перед каждым её изменением.

        Средняя очередь считается по времени, а не по числу наблюдений: очередь
        из трёхсот штук, простоявшая час, и очередь из трёхсот, мелькнувшая на
        минуту, — разные вещи, и усреднение по событиям их не различает.
        """
        span = now - self._marked
        if span > 0:
            grown = len(self.queue) * span
            self.stat.queue_area += grown
            if 0 <= month < len(self.stat.by_month_area):
                self.stat.by_month_area[month] += grown
        self._marked = now
        if len(self.queue) > self.stat.queue_peak:
            self.stat.queue_peak = len(self.queue)


@dataclass
class Result:
    """Итог прогона. Только числа — ни одного слова для человека.

    Формулировки живут отдельно и строятся уже поверх этого. Смешивать расчёт с
    рассказом означало бы, что изменить фразу нельзя без риска задеть число.
    """

    days: float
    completed: int
    demanded: int
    lead_days: float
    lead_p95_days: float
    late_share: float
    wip_end: int
    stations: tuple[dict, ...]
    revenue_month: float
    lost_month: float
    penalty_month: float
    payroll_month: float
    monthly: tuple[dict, ...]
    timeline: tuple[dict, ...]

    def station(self, station_id: str) -> dict:
        for item in self.stations:
            if item["id"] == station_id:
                return item
        raise KeyError(station_id)

    @property
    def bottleneck(self) -> dict:
        """Участок-ограничение.

        Выбирается по загрузке, но при равной загрузке решает накопленная
        очередь. Одной загрузки мало: два участка по девяносто восемь процентов
        выглядят одинаково в отчёте, а очередь растёт только перед тем, где
        разброс времени обработки больше. Ограничение — там, где копится.
        """
        return max(self.stations, key=lambda item: (item["load"], item["queue_avg"]))


def run(plant: Plant, months: int = 12, seed: int = 20260814) -> Result:
    """Прогоняет предприятие и возвращает числа.

    Время идёт в рабочих минутах. Заказы приходят пуассоновским потоком: он
    описывает независимые обращения клиентов, которые не сговариваются между
    собой, и именно его неравномерность создаёт очереди там, где средних
    мощностей формально хватает.
    """
    total_days = WARMUP_DAYS + months * WORK_DAYS_MONTH
    horizon = total_days * SHIFT_MINUTES
    warmup = WARMUP_DAYS * SHIFT_MINUTES
    counted_minutes = horizon - warmup
    counted_days = counted_minutes / SHIFT_MINUTES
    month_minutes = WORK_DAYS_MONTH * SHIFT_MINUTES

    slots = len(plant.stations) + _SLOTS_SPARE
    # Запас по числу заказов: поток пуассоновский, и фактическое количество за
    # горизонт колеблется вокруг среднего.
    capacity = int(plant.orders_day * total_days * 1.3) + 2000
    normals, uniforms = _draws(seed, capacity, slots)

    order: list[_Station] = []
    index: dict[str, int] = {}
    for position, source in enumerate(plant.stations):
        sigma = math.sqrt(math.log(1.0 + source.spread ** 2)) if source.spread > 0 else 0.0
        state = _Station(
            id=source.id, name=source.name, servers=source.staff,
            minutes=source.minutes, spread=source.spread,
            defect=source.defect, rework_to=source.rework_to,
            # Логнормальное распределение времени операции: оно не бывает
            # отрицательным. Нормальное при заметном разбросе даёт отрицательные
            # значения, отсечение которых смещает среднее вверх и тихо ломает
            # баланс модели. Логнормальное правдоподобно и по форме: редкие
            # долгие операции случаются, редкие мгновенные — нет.
            mu=math.log(max(source.minutes, 0.001)) - 0.5 * sigma * sigma,
            sigma=sigma,
            free=source.staff,
            stat=StationStat(id=source.id, name=source.name, staff=source.staff,
                             by_month_busy=[0.0] * months, by_month_area=[0.0] * months),
        )
        order.append(state)
        index[source.id] = position
    for state in order:
        if state.rework_to:
            state.rework_index = index[state.rework_to]

    # Событие — кортеж, а не словарь, и участок в нём лежит объектом, а не
    # именем. Порядковый номер `tick` уникален, поэтому куча никогда не
    # сравнивает то, что за ним, и складывать туда можно что угодно.
    events: list[tuple] = []
    tick = 0
    ARRIVE, FINISH = 0, 1

    def schedule(when: float, kind: int, payload) -> None:
        nonlocal tick
        tick += 1
        heapq.heappush(events, (when, tick, kind, payload))

    # Поток прихода заказов отдельный и общий для всех сценариев: клиенты не
    # знают, что на предприятии что-то поменяли, и обращаются так же, как раньше.
    arrivals = _random.Random(seed)
    rate = plant.orders_day / SHIFT_MINUTES
    schedule(arrivals.expovariate(rate), ARRIVE, None)

    lead_times: list[float] = []
    monthly: dict[int, dict] = {}
    wip_by_month = [0] * months
    completed = 0
    demanded = 0
    live: dict[int, dict] = {}
    next_id = 0
    seen_month = -1

    exp = math.exp

    def duration_at(station: _Station, job: dict) -> float:
        slot = job["slot"]
        job["slot"] = slot + 1 if slot + 1 < slots else 0
        if station.sigma <= 0.0:
            return station.minutes
        return max(0.5, exp(station.mu + station.sigma * normals[job["base"] + slot]))

    def admit(station: _Station, job: dict, now: float, month: int) -> None:
        """Ставит заказ на участок или в очередь к нему."""
        job["queued_at"] = now
        if station.free > 0:
            station.free -= 1
            job["started_at"] = now
            span = duration_at(station, job)
            schedule(now + span, FINISH, (station, job, span))
        else:
            station.touch(now, month)
            station.queue.append(job)
            station.touch(now, month)

    def release(station: _Station, now: float, month: int) -> None:
        """Освобождает человека и берёт следующий заказ из очереди."""
        if station.queue:
            station.touch(now, month)
            job = station.queue.popleft()
            station.touch(now, month)
            job["started_at"] = now
            span = duration_at(station, job)
            schedule(now + span, FINISH, (station, job, span))
        else:
            station.free += 1

    while events:
        now, _, kind, payload = heapq.heappop(events)
        if now > horizon:
            break

        counted = now >= warmup
        month = int((now - warmup) // month_minutes) if counted else -1
        if month >= months:
            break
        # Незавершёнка снимается на границе месяца: она и есть то, что растёт,
        # когда поток не справляется, и по одному итоговому числу этого не видно.
        if counted and month != seen_month:
            if 0 <= seen_month < months:
                wip_by_month[seen_month] = len(live)
            seen_month = month

        if kind == ARRIVE:
            next_id += 1
            job = {"id": next_id, "born": now, "step": 0,
                   "base": (next_id % capacity) * slots, "slot": 0}
            live[next_id] = job
            if counted:
                demanded += 1
            admit(order[0], job, now, month)
            schedule(now + arrivals.expovariate(rate), ARRIVE, None)
            continue

        station, job, span = payload

        if counted:
            # Занятость и ожидание учитываются только на зачётном отрезке, иначе
            # пустой разогрев занизит и загрузку, и очередь.
            station.stat.busy_minutes += span
            station.stat.by_month_busy[month] += span
            station.stat.wait_minutes += max(0.0, job["started_at"] - job["queued_at"])
            station.stat.served += 1

        goes_back = False
        if station.defect > 0.0 and station.rework_to:
            slot = job["slot"]
            job["slot"] = slot + 1 if slot + 1 < slots else 0
            # Жребий о браке берётся из строки заказа, а не из общего потока.
            # Заказ, признанный бракованным в одном сценарии, останется таким и в
            # другом: сравниваются способы организовать поток, а не удача изделий.
            goes_back = uniforms[job["base"] + slot] < station.defect

        if goes_back:
            if counted:
                station.stat.reworked += 1
            job["step"] = station.rework_index
            release(station, now, month)
            # Заказ, ушедший на переделку, встаёт в очередь заново — как и на
            # настоящем участке, без права пройти вне очереди.
            admit(order[job["step"]], job, now, month)
            continue

        release(station, now, month)
        job["step"] += 1
        if job["step"] < len(order):
            admit(order[job["step"]], job, now, month)
            continue

        live.pop(job["id"], None)
        if counted:
            completed += 1
            lead = (now - job["born"]) / SHIFT_MINUTES
            lead_times.append(lead)
            bucket = monthly.setdefault(month, {"month": month + 1, "completed": 0,
                                                "lead_sum": 0.0, "late": 0})
            bucket["completed"] += 1
            bucket["lead_sum"] += lead
            if lead > plant.late_after_days:
                bucket["late"] += 1

    for station in order:
        station.touch(min(horizon, max(warmup, station._marked)), min(seen_month, months - 1))
        station.stat.queue_end = len(station.queue)
    if 0 <= seen_month < months:
        wip_by_month[seen_month] = len(live)

    lead_times.sort()
    lead_avg = sum(lead_times) / max(len(lead_times), 1)
    lead_p95 = lead_times[int(len(lead_times) * 0.95)] if lead_times else 0.0
    late = sum(1 for value in lead_times if value > plant.late_after_days)
    late_share = late / max(len(lead_times), 1)

    months_counted = max(counted_days / WORK_DAYS_MONTH, 0.001)
    revenue_month = completed * plant.order_value / months_counted
    # Потеря — это маржа с заказов, которых спрос требовал, а поток не пропустил.
    # Считать здесь полную стоимость заказа было бы приятнее и неправдой.
    missed = max(0, demanded - completed)
    lost_month = missed * plant.order_value * plant.margin / months_counted
    penalty_month = late * plant.order_value * plant.penalty_share / months_counted

    series = []
    for number in range(months):
        bucket = monthly.get(number, {"month": number + 1, "completed": 0,
                                      "lead_sum": 0.0, "late": 0})
        series.append({
            "month": number + 1,
            "completed": bucket["completed"],
            "lead_days": bucket["lead_sum"] / max(bucket["completed"], 1),
            "late_share": bucket["late"] / max(bucket["completed"], 1),
            "wip": wip_by_month[number],
        })

    # Лента: снимок завода на каждый месяц. По ней интерфейс проигрывает год
    # вперёд — единственный способ показать, что очередь не стоит на месте, а
    # растёт, и что решение, отложенное на квартал, стоит вчетверо дороже.
    timeline = []
    for number in range(months):
        frame = series[number]
        timeline.append({
            "month": number + 1,
            "completed": frame["completed"],
            "lead_days": frame["lead_days"],
            "late_share": frame["late_share"],
            "wip": frame["wip"],
            "revenue": frame["completed"] * plant.order_value,
            "stations": {
                item.id: {
                    "load": item.stat.by_month_busy[number] / max(month_minutes * item.servers, 1.0),
                    "queue": item.stat.by_month_area[number] / month_minutes,
                }
                for item in order
            },
        })

    return Result(
        days=counted_days,
        completed=completed,
        demanded=demanded,
        lead_days=lead_avg,
        lead_p95_days=lead_p95,
        late_share=late_share,
        wip_end=len(live),
        stations=tuple(item.stat.summary(counted_minutes, counted_days) for item in order),
        revenue_month=revenue_month,
        lost_month=lost_month,
        penalty_month=penalty_month,
        payroll_month=plant.payroll_month,
        monthly=tuple(series),
        timeline=tuple(timeline),
    )
