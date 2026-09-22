"""Модель предприятия для цифрового двойника.

Предприятие описано декларативно: участки, люди на них, время обработки и связи
между участками. Это главное решение файла. Смысл всей затеи — сценарии «а что
если», а сценарий есть не что иное, как другая версия этих же чисел. Если бы
модель жила в коде, каждый вопрос директора требовал бы правки кода.

Единица времени везде — рабочая минута, не календарная. Календарь добавляет
смены, выходные и праздники, но ни на одну из величин, которые здесь считаются,
он не влияет: очередь растёт от соотношения спроса и пропускной способности, а
не от того, как эти минуты разложены по календарю. Пересчёт в дни и месяцы
делается на выходе, один раз, и только для показа человеку.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

# Рабочий день и месяц. Вынесено в константы, потому что эти два числа
# превращают минуты симуляции в рубли отчёта и встречаются в расчётах повсюду.
SHIFT_MINUTES = 480.0
WORK_DAYS_MONTH = 21


@dataclass(frozen=True)
class Station:
    """Участок производственного потока.

    `minutes` — время обработки одной единицы одним человеком. `spread` —
    коэффициент вариации этого времени: ноль означал бы конвейер, где каждая
    операция занимает ровно одинаково, а такого не бывает ни на одном реальном
    участке. Именно разброс, а не среднее, создаёт очереди при загрузке ниже ста
    процентов, и без него модель врёт в оптимистичную сторону.
    """

    id: str
    name: str
    staff: int
    minutes: float
    spread: float = 0.35
    defect: float = 0.0           # доля, уходящая на переделку
    rework_to: str | None = None  # куда возвращается брак
    salary_hour: float = 400.0
    role: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def capacity_day(self) -> float:
        """Сколько единиц участок способен пропустить за смену."""
        return self.staff * SHIFT_MINUTES / max(self.minutes, 0.001)

    @property
    def cost_month(self) -> float:
        """Фонд оплаты участка за месяц."""
        return self.staff * self.salary_hour * (SHIFT_MINUTES / 60.0) * WORK_DAYS_MONTH


@dataclass(frozen=True)
class Plant:
    """Предприятие целиком: маршрут, спрос и деньги.

    `margin` — доля выручки, остающаяся после переменных затрат. Через неё
    считается цена потерянного заказа: терять заказ означает терять маржу, а не
    всю его стоимость, и путать это — самый частый способ получить красивую, но
    неправдивую цифру экономии.
    """

    name: str
    stations: tuple[Station, ...]
    orders_day: float
    order_value: float
    margin: float = 0.18
    late_after_days: float = 7.0
    penalty_share: float = 0.04   # доля стоимости, теряемая на просроченном заказе
    # Во что обходится снижение брака вдвое, в долях месячного фонда оплаты
    # участка: обучение, оснастка, входной контроль. Допущение объявлено здесь,
    # в описании предприятия, а не спрятано в расчёте, — потому что это именно
    # допущение, и директор вправе спросить, откуда оно, и поменять его.
    quality_cost_share: float = 0.45

    def station(self, station_id: str) -> Station:
        for item in self.stations:
            if item.id == station_id:
                return item
        raise KeyError(station_id)

    @property
    def route(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.stations)

    @property
    def payroll_month(self) -> float:
        return sum(item.cost_month for item in self.stations)

    @property
    def headcount(self) -> int:
        return sum(item.staff for item in self.stations)

    def demand_at(self, station_id: str) -> float:
        """Реальный поток через участок с учётом возвратов на переделку.

        Брак возвращается назад по маршруту и проходит участки повторно, поэтому
        поток внутри петли переделки больше входящего спроса. Считать загрузку по
        входящему спросу — значит не увидеть перегруз именно там, где он есть:
        петля переделки как раз и создаётся перегруженным контролем.
        """
        index = {item.id: pos for pos, item in enumerate(self.stations)}
        here = index[station_id]
        flow = self.orders_day
        for item in self.stations:
            if not item.defect or item.rework_to is None:
                continue
            start, end = index[item.rework_to], index[item.id]
            if start <= here <= end:
                # Геометрическая сумма повторных проходов по петле.
                flow /= max(1.0 - item.defect, 0.05)
        return flow

    def load_at(self, station_id: str) -> float:
        """Оценка загрузки участка без запуска симуляции.

        Нужна интерфейсу: ползунок сценария должен отзываться мгновенно, пока
        честный расчёт ещё идёт в фоне. Оценка аналитическая и потому грубая —
        она не знает про очереди, — но направление всегда показывает верно.
        """
        return self.demand_at(station_id) / max(self.station(station_id).capacity_day, 0.001)

    def with_scenario(self, scenario: Scenario) -> Plant:
        """Новое предприятие с применённым сценарием. Исходное не меняется."""
        changed = []
        for item in self.stations:
            staff = max(1, item.staff + int(scenario.staff.get(item.id, 0)))
            minutes = item.minutes * float(scenario.speed.get(item.id, 1.0))
            defect = float(scenario.defect.get(item.id, item.defect))
            changed.append(replace(item, staff=staff, minutes=minutes, defect=defect))
        orders = self.orders_day * float(scenario.demand)
        return replace(self, stations=tuple(changed), orders_day=orders)


@dataclass(frozen=True)
class Scenario:
    """Отличие сценария от текущего состояния.

    Сценарий хранится как дельта, а не как полная копия предприятия. Так его
    можно показать человеку словами («плюс два контролёра»), сравнить два
    сценария между собой и объяснить, чем именно вызван результат.
    """

    staff: Mapping[str, int] = None          # type: ignore[assignment]
    speed: Mapping[str, float] = None        # type: ignore[assignment]
    defect: Mapping[str, float] = None       # type: ignore[assignment]
    demand: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "staff", dict(self.staff or {}))
        object.__setattr__(self, "speed", dict(self.speed or {}))
        object.__setattr__(self, "defect", dict(self.defect or {}))

    @property
    def empty(self) -> bool:
        return not (self.staff or self.speed or self.defect) and self.demand == 1.0

    def merged(self, other: Scenario) -> Scenario:
        """Сумма двух сценариев. Нужна перебору наборов мер."""
        staff = dict(self.staff)
        for key, value in other.staff.items():
            staff[key] = staff.get(key, 0) + value
        speed = dict(self.speed)
        for key, value in other.speed.items():
            speed[key] = speed.get(key, 1.0) * value
        defect = dict(self.defect)
        defect.update(other.defect)
        return Scenario(staff=staff, speed=speed, defect=defect,
                        demand=self.demand * other.demand)

    def describe(self, plant: Plant) -> str:
        """Сценарий человеческими словами — для реплики и для подписи в отчёте."""
        parts: list[str] = []
        for station_id, delta in self.staff.items():
            if not delta:
                continue
            name = plant.station(station_id).name
            parts.append(f"{'+' if delta > 0 else ''}{delta} чел. на участке «{name}»")
        for station_id, factor in self.speed.items():
            if factor == 1.0:
                continue
            name = plant.station(station_id).name
            change = round((1.0 - factor) * 100)
            parts.append(f"«{name}» быстрее на {change}%" if change > 0
                         else f"«{name}» медленнее на {-change}%")
        for station_id, share in self.defect.items():
            name = plant.station(station_id).name
            parts.append(f"брак на «{name}» — {share * 100:.0f}%")
        if self.demand != 1.0:
            parts.append(f"спрос {'+' if self.demand > 1 else ''}{(self.demand - 1) * 100:.0f}%")
        return ", ".join(parts) if parts else "без изменений"


# --------------------------------------------------------------------------- #
# Демонстрационное предприятие
# --------------------------------------------------------------------------- #
#
# Завод на четыре миллиарда выручки в год: двести десять заказов в день, двести
# сорок два человека, четырнадцать переделов. Масштаб взят не для внушительности
# цифры — на нём начинают работать эффекты, которых на маленьком потоке просто
# не видно. Один перегруженный участок среди четырнадцати останавливает завод
# целиком, и именно это невозможно объяснить таблицей.
#
# Планировка — подковой, в два пролёта, как на настоящем производстве: поток
# идёт по одной стороне и возвращается по другой. Вытянутая в линию цепочка из
# четырнадцати участков потребовала бы отвести камеру так далеко, что человек на
# площадке превратился бы в точку.
#
# Заложены два узла напряжения и две петли брака:
#   · ОТК загружен выше ста процентов — очередь перед ним растёт неограниченно;
#   · сварка идёт на девяноста трёх, и именно она станет ограничением, как
#     только ОТК расшить.
# Второе и есть главный урок демонстрации: узкое место не исчезает, а переезжает.

_ROW_A = -5.5     # прямой пролёт: от приёма заказов до механообработки
_ROW_B = 4.5      # обратный пролёт: от сварки до отгрузки

PLANT = Plant(
    name="Завод металлоконструкций",
    orders_day=210.0,
    order_value=74_000.0,
    margin=0.18,
    late_after_days=7.0,
    stations=(
        Station(id="intake", name="Приём заказов", role="Отдел продаж",
                staff=12, minutes=18.0, spread=0.30, salary_hour=380.0,
                position=(-13.0, 0.0, _ROW_A)),
        Station(id="design", name="Инженерная проработка", role="Конструкторский отдел",
                staff=21, minutes=34.0, spread=0.48, salary_hour=560.0,
                position=(-9.6, 0.0, _ROW_A)),
        Station(id="estimate", name="Расчёт и калькуляция", role="Планово-экономический",
                staff=10, minutes=16.0, spread=0.35, salary_hour=490.0,
                position=(-6.2, 0.0, _ROW_A)),
        Station(id="supply", name="Снабжение", role="Закупки",
                staff=13, minutes=20.0, spread=0.55, salary_hour=450.0,
                position=(-2.8, 0.0, _ROW_A)),
        Station(id="incoming", name="Входной контроль", role="Служба качества",
                staff=7, minutes=11.0, spread=0.40, defect=0.06, rework_to="supply",
                salary_hour=430.0, position=(0.6, 0.0, _ROW_A)),
        Station(id="cutting", name="Раскрой", role="Заготовительный участок",
                staff=16, minutes=26.0, spread=0.26, salary_hour=420.0,
                position=(4.0, 0.0, _ROW_A)),
        Station(id="machining", name="Механообработка", role="Станочный парк",
                staff=31, minutes=55.0, spread=0.32, salary_hour=520.0,
                position=(7.4, 0.0, _ROW_A)),
        Station(id="welding", name="Сварка", role="Сварочный участок",
                staff=29, minutes=62.0, spread=0.38, salary_hour=580.0,
                position=(7.4, 0.0, _ROW_B)),
        Station(id="coating", name="Окраска и покрытие", role="Малярный участок",
                staff=17, minutes=28.0, spread=0.30, salary_hour=440.0,
                position=(4.0, 0.0, _ROW_B)),
        Station(id="assembly", name="Сборка", role="Основное производство",
                staff=41, minutes=74.0, spread=0.34, salary_hour=500.0,
                position=(0.6, 0.0, _ROW_B)),
        Station(id="quality", name="Контроль качества", role="ОТК",
                staff=10, minutes=21.0, spread=0.42, defect=0.12, rework_to="assembly",
                salary_hour=470.0, position=(-2.8, 0.0, _ROW_B)),
        Station(id="packing", name="Упаковка", role="Участок упаковки",
                staff=12, minutes=19.0, spread=0.24, salary_hour=370.0,
                position=(-6.2, 0.0, _ROW_B)),
        Station(id="warehouse", name="Склад готовой продукции", role="Складское хозяйство",
                staff=10, minutes=15.0, spread=0.30, salary_hour=390.0,
                position=(-9.6, 0.0, _ROW_B)),
        Station(id="shipping", name="Отгрузка", role="Логистика",
                staff=13, minutes=22.0, spread=0.42, salary_hour=410.0,
                position=(-13.0, 0.0, _ROW_B)),
    ),
)
