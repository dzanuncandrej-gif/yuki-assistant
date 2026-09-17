"""Смысловой слой: вопрос превращается в числа, и только в числа.

Здесь проходит граница, ради которой всё и затевалось. Языковая модель в этом
файле не участвует — она получит готовые величины уже дальше и будет только
рассказывать. Причина простая: одно выдуманное число, произнесённое вслух перед
директором, уничтожает доверие ко всем остальным, и восстановить его нечем.
Поэтому считает симуляция, а не модель, а модель не имеет к расчёту доступа.

Каждая метрика возвращает ещё и участок, на который нужно навести камеру. Число
и место должны приходить вместе: ответ «узкое место на контроле» весит совсем
иначе, когда камера в этот момент уже стоит перед контролем.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .model import WORK_DAYS_MONTH, Plant, Scenario
from .sim import Result, run

MONTHS = 12

# Перебор ходов считает на укороченном горизонте, показ — на полном. Прогон года
# стоит полторы секунды, а перебор трогает их десятками; на четырёх месяцах
# порядок вариантов тот же — очередь перед узким местом успевает вырасти и
# развести варианты, — но обходится он вчетверо дешевле. Победитель после
# перебора обязательно пересчитывается на полном горизонте: ранжировать по
# грубому и показывать грубое — разные вещи.
SEARCH_MONTHS = 4


@lru_cache(maxsize=512)
def simulate(plant: Plant, months: int = MONTHS) -> Result:
    """Прогон с запоминанием.

    Предприятие неизменяемо и потому годится в ключ. Это важнее, чем кажется:
    один вопрос директора трогает три-четыре сценария, а ползунок сценария —
    десятки в секунду, и без кэша каждое движение считало бы год заново.
    """
    return run(plant, months=months)


# --------------------------------------------------------------------------- #
# Числа словами
# --------------------------------------------------------------------------- #

def plural(count: float, one: str, few: str, many: str) -> str:
    """Форма существительного при числе.

    Дробное число всегда требует родительного падежа единственного числа: «9,5
    дня», «1,7 миллиона». Округление до целого перед выбором формы — обычная
    ошибка, и на экране она почти незаметна, а вслух режет с первого слова.
    """
    if count != int(count):
        return few
    number = abs(int(count))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def money(value: float) -> str:
    """Деньги для показа на экране."""
    sign = "−" if value < 0 else ""
    value = abs(value)
    if value >= 1e9:
        return f"{sign}{value / 1e9:.2f} млрд ₽".replace(".", ",")
    if value >= 1e6:
        return f"{sign}{value / 1e6:.1f} млн ₽".replace(".", ",")
    if value >= 1e3:
        return f"{sign}{value / 1e3:.0f} тыс ₽"
    return f"{sign}{value:.0f} ₽"


def money_speech(value: float) -> str:
    """Те же деньги для произнесения вслух.

    Сокращения на экране читаются мгновенно, а вслух звучат как аббревиатура и
    сбивают: «млн» синтезатор произносит буквами. Поэтому для голоса — слова.
    """
    sign = "минус " if value < 0 else ""
    value = abs(value)
    if value >= 1e9:
        number = round(value / 1e9, 2)
        return f"{sign}{number:.2f}".replace(".", ",") + " " + plural(number, "миллиард", "миллиарда", "миллиардов") + " рублей"
    if value >= 1e6:
        number = round(value / 1e6, 1)
        return f"{sign}{number:.1f}".replace(".", ",") + " " + plural(number, "миллион", "миллиона", "миллионов") + " рублей"
    if value >= 1e3:
        return f"{sign}{value / 1e3:.0f} " + plural(value / 1e3, "тысяча", "тысячи", "тысяч") + " рублей"
    return f"{sign}{value:.0f} " + plural(value, "рубль", "рубля", "рублей")


def days(value: float) -> str:
    shown = round(value, 1)
    return f"{shown:.1f}".replace(".", ",") + " " + plural(shown, "день", "дня", "дней")


def months(value: float) -> str:
    if value < 1.0:
        weeks = max(1, round(value * 4.3))
        return f"{weeks} " + plural(weeks, "неделя", "недели", "недель")
    shown = round(value, 1)
    return f"{shown:.1f}".replace(".", ",") + " " + plural(shown, "месяц", "месяца", "месяцев")


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


# --------------------------------------------------------------------------- #
# Результат обращения к слою
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Fact:
    """Один установленный факт: подпись, значение на экран и значение вслух."""

    key: str
    label: str
    display: str
    speech: str
    accent: str = "plain"     # plain | good | bad — как подсветить в интерфейсе


@dataclass(frozen=True)
class Reading:
    """Ответ смыслового слоя: факты, куда смотреть и что показать."""

    metric: str
    title: str
    facts: tuple[Fact, ...]
    focus: str | None = None
    camera: str = "orbit"          # orbit | dive | wide | sweep
    scenario: Scenario | None = None
    series: tuple[dict, ...] = ()
    chart: str = ""

    def brief(self) -> str:
        """Факты одной строкой — это и есть то, что получит языковая модель."""
        return "; ".join(f"{item.label}: {item.speech}" for item in self.facts)


def _fact(key: str, label: str, display: str, speech: str = "", accent: str = "plain") -> Fact:
    return Fact(key=key, label=label, display=display, speech=speech or display, accent=accent)


# --------------------------------------------------------------------------- #
# Метрики
# --------------------------------------------------------------------------- #

def overview(plant: Plant) -> Reading:
    base = simulate(plant)
    neck = base.bottleneck
    return Reading(
        metric="overview",
        title="Общая картина",
        focus=neck["id"],
        camera="wide",
        facts=(
            _fact("revenue", "Выручка в месяц", money(base.revenue_month),
                  money_speech(base.revenue_month)),
            _fact("lead", "Срок выполнения заказа", days(base.lead_days),
                  days(base.lead_days), "bad" if base.lead_days > plant.late_after_days else "good"),
            _fact("late", "Просрочено", percent(base.late_share), percent(base.late_share),
                  "bad" if base.late_share > 0.1 else "good"),
            _fact("neck", "Узкое место", f"{neck['name']} — {percent(neck['load'])}",
                  f"{neck['name']}, загрузка {percent(neck['load'])}", "bad"),
            _fact("wip", "Незавершёнка", f"{base.wip_end} " + plural(base.wip_end, "заказ", "заказа", "заказов"),
                  f"{base.wip_end} " + plural(base.wip_end, "заказ", "заказа", "заказов")),
        ),
        series=base.monthly,
        chart="lead",
    )


def bottleneck(plant: Plant) -> Reading:
    """Где ограничение и куда оно переедет, если ограничение снять.

    Второй вопрос здесь важнее первого. Узкое место видно и по отчёту; чего по
    отчёту не видно — что оно не исчезает, а перемещается. Директор, который
    этого не знает, расшивает участок, не получает обещанного эффекта и делает
    вывод, что улучшения не работают.
    """
    base = simulate(plant)
    neck = base.bottleneck
    station = plant.station(neck["id"])

    relieved = simulate(plant.with_scenario(Scenario(staff={neck["id"]: 1})))
    moved = relieved.bottleneck

    facts = [
        _fact("where", "Узкое место", f"{station.name} ({station.role})",
              f"участок {station.name}", "bad"),
        _fact("load", "Загрузка", percent(neck["load"]), f"загрузка {percent(neck['load'])}", "bad"),
        _fact("queue", "Очередь перед участком",
              f"{neck['queue_avg']:.0f} " + plural(neck["queue_avg"], "заказ", "заказа", "заказов")
              + f" (пик {neck['queue_peak']})",
              f"в среднем {neck['queue_avg']:.0f} " + plural(neck["queue_avg"], "заказ", "заказа", "заказов"),
              "bad"),
        _fact("wait", "Ожидание в этой очереди", days(neck["wait_days"]),
              f"заказ ждёт здесь {days(neck['wait_days'])}", "bad"),
        _fact("share", "Доля в общем сроке",
              percent(neck["wait_days"] / max(base.lead_days, 0.01)),
              f"это {percent(neck['wait_days'] / max(base.lead_days, 0.01))} всего срока"),
    ]
    if moved["id"] != neck["id"]:
        facts.append(_fact(
            "next", "Если расшить — переедет на",
            f"{moved['name']} ({percent(moved['load'])})",
            f"если добавить сюда человека, ограничением станет {moved['name']} "
            f"с загрузкой {percent(moved['load'])}",
        ))
    return Reading(metric="bottleneck", title="Узкое место", facts=tuple(facts),
                   focus=neck["id"], camera="dive")


def lead_time(plant: Plant) -> Reading:
    base = simulate(plant)
    worst = max(base.stations, key=lambda item: item["wait_days"])
    return Reading(
        metric="lead_time",
        title="Срок выполнения",
        focus=worst["id"],
        camera="dive",
        facts=(
            _fact("avg", "В среднем", days(base.lead_days), days(base.lead_days),
                  "bad" if base.lead_days > plant.late_after_days else "good"),
            _fact("p95", "Девяносто пятый процентиль", days(base.lead_p95_days),
                  f"каждый двадцатый заказ идёт дольше {days(base.lead_p95_days)}", "bad"),
            _fact("late", "Просрочено относительно "
                          + days(plant.late_after_days), percent(base.late_share),
                  f"просрочено {percent(base.late_share)} заказов", "bad"),
            _fact("worst", "Больше всего ждут на", worst["name"],
                  f"дольше всего заказ стоит на участке {worst['name']}: {days(worst['wait_days'])}"),
        ),
        series=base.monthly,
        chart="lead",
    )


def losses(plant: Plant) -> Reading:
    """Во что обходится текущее состояние.

    Считается не «сколько мог бы заработать идеальный завод», а разница между
    тем, что спрос принёс, и тем, что поток пропустил. Первое считать приятнее,
    но эта цифра не выдерживает ни одного уточняющего вопроса.
    """
    base = simulate(plant)
    ideal = simulate(plant.with_scenario(Scenario(staff={
        item["id"]: 3 for item in base.stations if item["load"] > 0.85
    })))
    upside = (ideal.revenue_month - base.revenue_month) * plant.margin
    stuck = base.wip_end * plant.order_value
    return Reading(
        metric="losses",
        title="Потери",
        focus=base.bottleneck["id"],
        camera="dive",
        facts=(
            _fact("blocked", "Заморожено в незавершёнке", money(stuck), money_speech(stuck), "bad"),
            _fact("penalty", "Потери на просрочках в месяц", money(base.penalty_month),
                  money_speech(base.penalty_month), "bad"),
            _fact("upside", "Недополученная маржа в месяц", money(upside),
                  money_speech(upside), "bad"),
            _fact("year", "То же за год", money(upside * 12 + base.penalty_month * 12),
                  money_speech(upside * 12 + base.penalty_month * 12), "bad"),
        ),
    )


def throughput(plant: Plant) -> Reading:
    base = simulate(plant)
    done = base.completed / max(base.days, 1)
    gap = plant.orders_day - done
    return Reading(
        metric="throughput",
        title="Пропускная способность",
        focus=base.bottleneck["id"],
        camera="sweep",
        facts=(
            _fact("demand", "Спрос", f"{plant.orders_day:.0f} заказов в день",
                  f"{plant.orders_day:.0f} " + plural(plant.orders_day, "заказ", "заказа", "заказов") + " в день"),
            _fact("done", "Проходит", f"{done:.1f} в день".replace(".", ","),
                  f"проходит {done:.1f}".replace(".", ",") + " в день",
                  "bad" if gap > 0.5 else "good"),
            _fact("gap", "Не проходит", f"{max(gap, 0):.1f} в день".replace(".", ","),
                  f"не проходит {max(gap, 0):.1f}".replace(".", ",") + " в день", "bad"),
            _fact("year", "За год недоделано",
                  f"{max(gap, 0) * WORK_DAYS_MONTH * 12:.0f} заказов",
                  f"за год это {max(gap, 0) * WORK_DAYS_MONTH * 12:.0f} "
                  + plural(max(gap, 0) * WORK_DAYS_MONTH * 12, "заказ", "заказа", "заказов"), "bad"),
        ),
    )


def utilization(plant: Plant) -> Reading:
    base = simulate(plant)
    ranked = sorted(base.stations, key=lambda item: -item["load"])
    facts = tuple(
        _fact(item["id"], item["name"], percent(item["load"]),
              f"{item['name']} — {percent(item['load'])}",
              "bad" if item["load"] > 0.9 else "good" if item["load"] < 0.75 else "plain")
        for item in ranked
    )
    return Reading(metric="utilization", title="Загрузка участков", facts=facts,
                   focus=ranked[0]["id"], camera="sweep")


def rework(plant: Plant) -> Reading:
    """Цена переделок. Считается по времени, которое они съедают, а не по штукам.

    Штуки брака звучат безобидно: двенадцать процентов кажутся допустимыми. Те
    же двенадцать процентов, пересчитанные в часы сборки и в занятую мощность
    узкого участка, выглядят совсем иначе — и именно так их стоит показывать.
    """
    base = simulate(plant)
    source = next((item for item in plant.stations if item.defect > 0), None)
    if source is None:
        return Reading(metric="rework", title="Переделки", focus=None,
                       facts=(_fact("none", "Переделки", "в модели не заданы"),))
    stat = base.station(source.id)
    back = plant.station(source.rework_to or source.id)
    back_stat = base.station(back.id)
    extra_minutes = stat["reworked"] * back.minutes
    extra_cost = extra_minutes / 60.0 * back.salary_hour / max(base.days / WORK_DAYS_MONTH, 0.01)
    clean = simulate(plant.with_scenario(Scenario(defect={source.id: 0.03})))
    return Reading(
        metric="rework",
        title="Переделки",
        focus=source.id,
        camera="dive",
        facts=(
            _fact("rate", "Доля брака на " + source.name, percent(source.defect),
                  f"брак на участке {source.name} — {percent(source.defect)}", "bad"),
            _fact("count", "Возвратов за год", f"{stat['reworked']}",
                  f"{stat['reworked']} " + plural(stat["reworked"], "возврат", "возврата", "возвратов") + " за год", "bad"),
            _fact("time", "Съедено мощности " + back.name,
                  percent(stat["reworked"] / max(back_stat["served"], 1)),
                  f"переделки съедают {percent(stat['reworked'] / max(back_stat['served'], 1))} "
                  f"мощности участка {back.name}", "bad"),
            _fact("cost", "Стоимость переделок в месяц", money(extra_cost), money_speech(extra_cost), "bad"),
            _fact("if", "Если снизить брак до 3%",
                  f"срок {days(clean.lead_days)}, просрочка {percent(clean.late_share)}",
                  f"при браке три процента срок станет {days(clean.lead_days)}, "
                  f"просрочка {percent(clean.late_share)}", "good"),
        ),
    )


def payroll(plant: Plant) -> Reading:
    base = simulate(plant)
    ranked = sorted(plant.stations, key=lambda item: -item.cost_month)
    facts = [_fact("total", "Фонд оплаты в месяц", money(plant.payroll_month),
                   money_speech(plant.payroll_month))]
    facts.append(_fact("share", "Доля от выручки",
                       percent(plant.payroll_month / max(base.revenue_month, 1)),
                       f"это {percent(plant.payroll_month / max(base.revenue_month, 1))} выручки"))
    facts += [
        _fact(item.id, item.name, f"{item.staff} чел. — {money(item.cost_month)}",
              f"{item.name}: {item.staff} " + plural(item.staff, "человек", "человека", "человек"))
        for item in ranked[:4]
    ]
    return Reading(metric="payroll", title="Люди и деньги", facts=tuple(facts),
                   focus=ranked[0].id, camera="sweep")


# --------------------------------------------------------------------------- #
# Сценарии
# --------------------------------------------------------------------------- #

def compare(plant: Plant, scenario: Scenario) -> Reading:
    """Что даст изменение. Главный инструмент разговора.

    Считается чистый эффект: прирост маржи минус прирост фонда оплаты. Показывать
    один прирост выручки — обычная и приятная ошибка: она превращает любое
    добавление людей в выгодное решение, потому что людей в этой арифметике
    просто нет.
    """
    base = simulate(plant)
    alt = simulate(plant.with_scenario(scenario))

    gain_margin = (alt.revenue_month - base.revenue_month) * plant.margin
    gain_penalty = base.penalty_month - alt.penalty_month
    cost = alt.payroll_month - base.payroll_month
    net = gain_margin + gain_penalty - cost
    payback = (cost / net) if net > 0 and cost > 0 else 0.0

    neck = alt.bottleneck
    facts = [
        _fact("what", "Сценарий", scenario.describe(plant), scenario.describe(plant)),
        # Разница даётся готовой, а не оставляется на вычитание в реплике.
        # Модель считает такую разницу верно почти всегда — и «почти» здесь
        # лишнее: любое число в ответе должно приходить из расчёта.
        _fact("lead", "Срок выполнения",
              f"{days(base.lead_days)} → {days(alt.lead_days)}",
              f"срок выполнения меняется с {days(base.lead_days)} на {days(alt.lead_days)}, "
              f"это {'быстрее' if alt.lead_days < base.lead_days else 'дольше'} на "
              f"{days(abs(base.lead_days - alt.lead_days))}",
              "good" if alt.lead_days < base.lead_days else "bad"),
        _fact("late", "Просрочка",
              f"{percent(base.late_share)} → {percent(alt.late_share)}",
              f"просрочка с {percent(base.late_share)} до {percent(alt.late_share)}",
              "good" if alt.late_share < base.late_share else "bad"),
        _fact("cost", "Дополнительные затраты в месяц", money(cost), money_speech(cost)),
        _fact("net", "Чистый эффект в месяц", money(net), money_speech(net),
              "good" if net > 0 else "bad"),
        _fact("year", "Чистый эффект за год", money(net * 12), money_speech(net * 12),
              "good" if net > 0 else "bad"),
    ]
    if payback:
        facts.append(_fact("payback", "Окупаемость", months(payback),
                           f"окупается за {months(payback)}", "good"))
    if neck["id"] != base.bottleneck["id"]:
        facts.append(_fact("moved", "Узкое место переезжает на",
                           f"{neck['name']} ({percent(neck['load'])})",
                           f"после этого ограничением становится {neck['name']}, "
                           f"загрузка {percent(neck['load'])}"))
    return Reading(metric="scenario", title="Сценарий", facts=tuple(facts),
                   focus=neck["id"], camera="dive", scenario=scenario,
                   series=alt.monthly, chart="lead")


def best_move(plant: Plant) -> Reading:
    """Перебирает добавление одного человека на каждый участок и ранжирует.

    Это ответ на вопрос «что делать», и он должен быть найден, а не назначен.
    Перебор честный: восемь прогонов по году каждый, и выигрывает тот участок,
    где чистый эффект максимален, — а не тот, который громче всех жалуется.
    """
    base = simulate(plant)
    options = []
    for station in plant.stations:
        scenario = Scenario(staff={station.id: 1})
        alt = simulate(plant.with_scenario(scenario))
        gain = ((alt.revenue_month - base.revenue_month) * plant.margin
                + (base.penalty_month - alt.penalty_month))
        cost = alt.payroll_month - base.payroll_month
        options.append({
            "id": station.id, "name": station.name, "net": gain - cost,
            "lead": alt.lead_days, "late": alt.late_share,
        })
    options.sort(key=lambda item: -item["net"])
    top = options[0]
    second = options[1]
    return Reading(
        metric="best_move",
        title="Что делать",
        focus=top["id"],
        camera="dive",
        scenario=Scenario(staff={top["id"]: 1}),
        facts=(
            _fact("do", "Сильнейший ход", f"+1 человек на «{top['name']}»",
                  f"добавить одного человека на участок {top['name']}", "good"),
            _fact("net", "Чистый эффект за год", money(top["net"] * 12),
                  money_speech(top["net"] * 12), "good"),
            _fact("lead", "Срок выполнения",
                  f"{days(base.lead_days)} → {days(top['lead'])}",
                  f"срок падает с {days(base.lead_days)} до {days(top['lead'])}", "good"),
            _fact("late", "Просрочка", f"{percent(base.late_share)} → {percent(top['late'])}",
                  f"просрочка с {percent(base.late_share)} до {percent(top['late'])}", "good"),
            _fact("second", "Следующий по силе",
                  f"«{second['name']}» — {money(second['net'] * 12)} в год",
                  f"следующий по силе ход — {second['name']}, "
                  f"{money_speech(second['net'] * 12)} в год"),
        ),
    )


def station_detail(plant: Plant, station_id: str) -> Reading:
    base = simulate(plant)
    station = plant.station(station_id)
    stat = base.station(station_id)
    scenario = Scenario(staff={station_id: 1})
    alt = simulate(plant.with_scenario(scenario))
    gain = ((alt.revenue_month - base.revenue_month) * plant.margin
            + (base.penalty_month - alt.penalty_month)
            - (alt.payroll_month - base.payroll_month))
    return Reading(
        metric="station",
        title=station.name,
        focus=station_id,
        camera="dive",
        facts=(
            _fact("role", "Подразделение", station.role, station.role),
            _fact("staff", "Людей", f"{station.staff}",
                  f"{station.staff} " + plural(station.staff, "человек", "человека", "человек")),
            _fact("load", "Загрузка", percent(stat["load"]), f"загрузка {percent(stat['load'])}",
                  "bad" if stat["load"] > 0.9 else "good" if stat["load"] < 0.75 else "plain"),
            _fact("queue", "Средняя очередь", f"{stat['queue_avg']:.1f}".replace(".", ","),
                  f"средняя очередь {stat['queue_avg']:.0f}"),
            _fact("wait", "Ожидание", days(stat["wait_days"]), f"ожидание {days(stat['wait_days'])}"),
            _fact("plus", "Если добавить человека", money(gain * 12) + " в год",
                  f"добавленный сюда человек даёт {money_speech(gain * 12)} в год",
                  "good" if gain > 0 else "bad"),
        ),
    )
