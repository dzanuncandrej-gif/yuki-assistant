"""Вопрос человека превращается в обращение к смысловому слою.

Сначала — словарь, и только потом языковая модель. Порядок выбран из-за
задержки: разбор по словам занимает доли миллисекунды, обращение к модели —
сотни. Директор, спросивший «где узкое место», получит камеру в движении
раньше, чем успеет договорить, и именно это ощущение мгновенности делает
разговор с предприятием разговором, а не отправкой запроса.

Модель подключается там, где словарь честно не справился, — на длинных или
непрямых формулировках. Она выбирает метрику из списка и не имеет права
придумать свою: всё, что она вернёт вне списка, отбрасывается.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import metrics
from .model import Plant, Scenario

# Синонимы участков. Живут здесь, а не в модели предприятия: модель описывает
# производство, а это — про то, как о производстве говорят люди. Смешаешь одно
# с другим, и добавление синонима потребует правки описания завода.
ALIASES: dict[str, tuple[str, ...]] = {
    # «Клиент» нарочно не синоним приёма заказов: это слово встречается почти в
    # любом общем вопросе — «сколько ждут клиенты» относится ко всему потоку, а
    # не к отделу продаж, и как синоним оно уводило камеру не туда.
    "intake": ("приём", "прием", "продаж", "менеджер", "заявк", "приёмк", "приемк"),
    "design": ("проработ", "конструктор", "инженер", "чертеж", "чертёж", "проект", "технолог"),
    "supply": ("снабжен", "закуп", "поставщик", "материал", "комплектующ"),
    "cutting": ("раскрой", "заготов", "резк", "пил", "нарезк"),
    "assembly": ("сборк", "собира", "производств", "цех", "монтаж"),
    "quality": ("отк", "контрол", "качеств", "проверк", "брак", "дефект", "инспект"),
    "packing": ("упаков", "паллет", "склад готов"),
    "shipping": ("отгруз", "логистик", "доставк", "транспорт", "экспедиц"),
}

# Метрика подбирается по совпадениям. Вес важен: слово «узкое» указывает на
# ограничение куда увереннее, чем «где», и без весов длинный вопрос уводило бы
# в сторону случайное общее слово.
ROUTES: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = (
    ("bottleneck", (("узкое", 6), ("бутылочн", 6), ("ограничен", 5), ("тормоз", 5),
                    ("затык", 5), ("застрева", 4), ("пробк", 4), ("где проблем", 5),
                    ("что мешает", 5), ("не справля", 4))),
    ("losses", (("тер", 5), ("потер", 6), ("убыт", 6), ("недополуч", 6),
                ("сколько сто", 4), ("во что обход", 5), ("замороже", 4), ("сливаю", 4))),
    ("lead_time", (("срок", 6), ("долго", 5), ("быстро выполн", 5), ("ждут", 5),
                   ("ожидан", 4), ("цикл", 4), ("просроч", 5), ("вовремя", 4),
                   ("сколько дней", 5), ("лид", 3))),
    ("throughput", (("пропуск", 6), ("сколько дела", 5), ("сколько выпуск", 5),
                    ("объём", 4), ("объем", 4), ("мощност", 5), ("производительн", 5),
                    ("успева", 4), ("справля", 3))),
    ("utilization", (("загруз", 6), ("занят", 4), ("простаива", 5), ("бездельнич", 5),
                     ("кто свобод", 5), ("перегруж", 5), ("нагрузк", 5))),
    ("rework", (("брак", 6), ("передел", 6), ("возврат", 5), ("дефект", 5),
                ("качеств", 3), ("рекламац", 5))),
    ("payroll", (("зарплат", 6), ("фонд опл", 6), ("персонал", 4), ("штат", 5),
                 ("сколько люд", 5), ("сотрудник", 4), ("фот", 5))),
    ("best_move", (("делать", 6), ("предприн", 6), ("как исправ", 6), ("посоветуй", 7),
                   ("как улучш", 6), ("совет", 5), ("рекоменд", 5), ("с чего нач", 6),
                   ("куда вложи", 6), ("как ускор", 5), ("что мне", 4), ("реши", 4))),
    ("overview", (("как дела", 6), ("общая карт", 6), ("обзор", 6), ("расскажи о", 4),
                  ("покажи всё", 6), ("покажи все", 6), ("что происход", 5),
                  ("состоян", 4), ("итог", 4))),
)

# Числительные словами. Директор говорит «двух человек», а не «2 человек».
WORD_NUMBERS: dict[str, int] = {
    "один": 1, "одного": 1, "одну": 1, "два": 2, "двух": 2, "две": 2, "двоих": 2,
    "три": 3, "трёх": 3, "трех": 3, "троих": 3, "четыре": 4, "четырёх": 4,
    "четырех": 4, "пять": 5, "пяти": 5, "шесть": 6, "шести": 6,
}

ADD = ("добав", "найм", "нанят", "поставь", "постав", "усил", "прибав", "ещё", "еще",
       "дополнительн", "плюс")
REMOVE = ("убра", "убер", "сократ", "уволь", "снять", "минус", "меньше")
SPEED = ("быстре", "ускор", "автоматиз", "сократить время", "оптимизир")


@dataclass(frozen=True)
class Intent:
    """Что человек хотел: метрика, участок и, возможно, сценарий."""

    metric: str
    station: str | None = None
    scenario: Scenario | None = None
    source: str = "words"      # words | model | fallback


def _station_in(text: str) -> str | None:
    """Находит упоминание участка. Побеждает самое длинное совпадение.

    Длина важна: «склад готовой» и «склад» указывают на разное, и короткий
    синоним, проверенный первым, увёл бы к неверному участку.
    """
    best: tuple[int, str] | None = None
    for station_id, words in ALIASES.items():
        for word in words:
            if word in text and (best is None or len(word) > best[0]):
                best = (len(word), station_id)
    return best[1] if best else None


def _count_in(text: str) -> int:
    """Сколько человек. Ограничено сверху — двадцать разом никто не нанимает."""
    digits = re.search(r"\b(\d+)\b", text)
    if digits:
        return max(1, min(20, int(digits.group(1))))
    for word, value in WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", text):
            return value
    return 1


def _percent_in(text: str) -> float | None:
    """Сколько процентов. Считается отдельно от людей, и это не педантизм.

    Общий разбор чисел ограничивал значение двадцатью — разумно для людей и
    разрушительно для процентов: «ускорить на тридцать процентов» превращалось в
    двадцать, ответ расходился с вопросом, и заметить подмену в разговоре нельзя.
    """
    match = re.search(r"\b(\d{1,2})\s*(?:%|процент)", text)
    if match:
        return max(5, min(80, int(match.group(1)))) / 100.0
    for word, value in WORD_NUMBERS.items():
        if re.search(rf"\b{word}\s*(?:%|процент)", text):
            return value / 100.0
    return None


def _scenario_in(text: str, station: str | None) -> Scenario | None:
    """Собирает сценарий из фразы, если человек предложил изменение."""
    if station is None:
        return None
    if any(word in text for word in ADD):
        return Scenario(staff={station: _count_in(text)})
    if any(word in text for word in REMOVE):
        return Scenario(staff={station: -_count_in(text)})
    if any(word in text for word in SPEED):
        # «Быстрее» без названной доли означает заметное, но не фантастическое
        # ускорение: четверть времени — то, что даёт наведение порядка без техники.
        share = _percent_in(text) or 0.25
        return Scenario(speed={station: max(0.2, 1.0 - share)})
    return None


def by_words(question: str) -> Intent | None:
    """Разбор по словарю. Возвращает None, если уверенности нет."""
    text = question.lower().replace("ё", "ё")
    station = _station_in(text)
    scenario = _scenario_in(text, station)
    if scenario is not None:
        return Intent(metric="scenario", station=station, scenario=scenario)

    scores: dict[str, int] = {}
    for metric, words in ROUTES:
        score = sum(weight for word, weight in words if word in text)
        if score:
            scores[metric] = score
    if not scores:
        # Участок назван, а метрика — нет: человек спросил «а сборка?».
        return Intent(metric="station", station=station) if station else None

    metric = max(scores, key=lambda key: scores[key])
    if scores[metric] < 4:
        return None
    # Метрика про конкретный участок ценнее общей сводки по нему.
    if station and metric in ("utilization", "overview"):
        return Intent(metric="station", station=station)
    return Intent(metric=metric, station=station)


CHOICES = ("bottleneck", "losses", "lead_time", "throughput", "utilization",
           "rework", "payroll", "best_move", "overview")

_ASK = (
    "Ты маршрутизатор вопросов о производстве. Выбери ОДНО слово из списка, "
    "которое лучше всего отвечает на вопрос директора.\n"
    "Список: " + ", ".join(CHOICES) + "\n"
    "bottleneck — где ограничение, что тормозит поток\n"
    "losses — сколько денег теряется\n"
    "lead_time — сроки, ожидание, просрочки\n"
    "throughput — сколько заказов проходит\n"
    "utilization — загрузка людей и участков\n"
    "rework — брак и переделки\n"
    "payroll — персонал и фонд оплаты\n"
    "best_move — что делать, какие меры принять\n"
    "overview — общая картина\n"
    "Ответь ровно одним словом из списка, без пояснений."
)


def by_model(question: str, url: str, model: str) -> Intent:
    """Запасной разбор моделью. Ответ вне списка не принимается."""
    import requests

    try:
        session = requests.Session()
        session.trust_env = False
        answer = session.post(
            f"{url}/api/chat",
            json={
                "model": model, "stream": False, "keep_alive": "30m", "think": False,
                "messages": [{"role": "system", "content": _ASK},
                             {"role": "user", "content": question[:300]}],
                "options": {"num_predict": 8, "temperature": 0.0},
            },
            timeout=20,
        ).json()
        raw = str(answer.get("message", {}).get("content", "")).strip().lower()
    except Exception:
        raw = ""

    for choice in CHOICES:
        if choice in raw:
            return Intent(metric=choice, station=_station_in(question.lower()), source="model")
    return Intent(metric="overview", source="fallback")


def resolve(question: str, url: str = "", model: str = "") -> Intent:
    found = by_words(question)
    if found is not None:
        return found
    if url and model:
        return by_model(question, url, model)
    return Intent(metric="overview", source="fallback")


HANDLERS = {
    "overview": metrics.overview,
    "bottleneck": metrics.bottleneck,
    "lead_time": metrics.lead_time,
    "losses": metrics.losses,
    "throughput": metrics.throughput,
    "utilization": metrics.utilization,
    "rework": metrics.rework,
    "payroll": metrics.payroll,
    "best_move": metrics.best_move,
}


def read(plant: Plant, intent: Intent) -> metrics.Reading:
    """Выполняет разобранное намерение и возвращает числа."""
    if intent.metric == "scenario" and intent.scenario is not None:
        return metrics.compare(plant, intent.scenario)
    if intent.metric == "station" and intent.station:
        return metrics.station_detail(plant, intent.station)
    handler = HANDLERS.get(intent.metric, metrics.overview)
    reading = handler(plant)
    # Спросили про метрику, назвав участок: показываем метрику, но камеру
    # уводим туда, куда смотрит человек, — иначе он потеряет связь с ответом.
    if intent.station and reading.focus != intent.station and intent.metric in ("utilization",):
        return metrics.station_detail(plant, intent.station)
    return reading
