"""Сценарии: несколько действий под одним именем, запускаемые одной фразой.

«Юки, рабочий режим» — и она открывает нужные программы, ставит громкость,
включает музыку. Смысл не в экономии слов, а в том, что распорядок дня перестаёт
быть чередой отдельных просьб.

Сценарий — это список шагов, каждый из которых вызывает обычный инструмент. Ничего
нового выполнять не приходится: сценарий просто складывает уже имеющиеся умения в
последовательность. Поэтому в нём работает и запуск программ, и экран, и
громкость — всё, что Юки умеет поодиночке.

Шаги выполняются по очереди, и упавший шаг не обрывает остальные: если Steam не
установлен, это не повод не открыть браузер. В конце возвращается честный отчёт —
что получилось, а что нет.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from . import config

STORE = config.ROOT / "data" / "workflows.json"
_lock = threading.Lock()

# дольше этого один сценарий не выполняется: зависший шаг не должен держать всё
STEP_LIMIT_S = 45.0


class WorkflowError(RuntimeError):
    """Сценарий не найден или описан неверно."""


@dataclass(frozen=True)
class Step:
    """Один шаг: вызов инструмента с готовыми доводами."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def describe(self) -> str:
        if self.note:
            return self.note
        body = ", ".join(f"{key}={value}" for key, value in self.arguments.items())
        return f"{self.tool}({body})" if body else self.tool


@dataclass(frozen=True)
class Workflow:
    """Именованный сценарий."""

    name: str
    title: str
    steps: tuple[Step, ...]
    say: str = ""          # что сказать вслух после выполнения
    builtin: bool = False

    def describe(self) -> str:
        return f"{self.title}: " + " → ".join(step.describe() for step in self.steps)


# Готовые сценарии. Они не «примеры для галочки»: это то, что человек за
# компьютером делает каждый день по нескольку раз, каждый раз отдельными
# просьбами. Их можно менять и удалять — как и свои.
BUILTIN: tuple[Workflow, ...] = (
    Workflow(
        name="рабочий режим",
        title="Рабочий режим",
        steps=(
            Step("volume_set", {"level": 25}, "приглушить звук"),
            Step("open_app", {"name": "chrome"}, "открыть браузер"),
            Step("open_app", {"name": "telegram"}, "открыть телеграм"),
        ),
        say="Рабочий режим включён.",
        builtin=True,
    ),
    Workflow(
        name="отдых",
        title="Отдых",
        steps=(
            Step("volume_set", {"level": 55}, "вернуть звук"),
            Step("play_music", {"query": "spokojnaya muzyka"}, "включить музыку"),
        ),
        say="Отдыхаем.",
        builtin=True,
    ),
    Workflow(
        name="что у меня происходит",
        title="Сводка",
        steps=(
            Step("get_time", {}, "время"),
            Step("get_weather", {}, "погода"),
            Step("system_stats", {}, "состояние компьютера"),
            Step("list_timers", {}, "напоминания"),
        ),
        say="",
        builtin=True,
    ),
    Workflow(
        name="закончить работу",
        title="Закончить работу",
        steps=(
            Step("window_control", {"action": "minimize_all"}, "свернуть окна"),
            Step("volume_set", {"level": 15}, "убавить звук"),
        ),
        say="Всё свернула. Хорошего вечера.",
        builtin=True,
    ),
)


# ---------------------------------------------------------------- хранилище


def _load_custom() -> list[Workflow]:
    if not STORE.exists():
        return []
    try:
        raw = json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    found: list[Workflow] = []
    for item in raw.get("workflows", []) if isinstance(raw, dict) else []:
        try:
            steps = tuple(
                Step(str(step["tool"]), dict(step.get("arguments", {})), str(step.get("note", "")))
                for step in item.get("steps", []) if step.get("tool")
            )
            if not steps:
                continue
            found.append(Workflow(
                name=str(item["name"]).strip().lower(),
                title=str(item.get("title") or item["name"]),
                steps=steps,
                say=str(item.get("say", "")),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return found


def _save_custom(items: Sequence[Workflow]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workflows": [
            {
                "name": item.name,
                "title": item.title,
                "say": item.say,
                "steps": [asdict(step) for step in item.steps],
            }
            for item in items if not item.builtin
        ]
    }
    STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def catalog() -> tuple[Workflow, ...]:
    """Все сценарии: свои поверх готовых. Одноимённый свой заменяет готовый."""
    with _lock:
        custom = _load_custom()
    names = {item.name for item in custom}
    return tuple(custom) + tuple(item for item in BUILTIN if item.name not in names)


def get(name: str) -> Workflow | None:
    needle = str(name or "").strip().lower()
    if not needle:
        return None
    items = catalog()
    # Искать надо и по названию, которое человек видит на экране. Сценарий
    # «что у меня происходит» подписан «Сводка», и просьба «сделай сводку»
    # не находила ничего, хотя кнопка с этим словом была прямо перед глазами.
    for item in items:
        if needle in (item.name, item.title.strip().lower()):
            return item
    for item in items:
        for label in (item.name, item.title.strip().lower()):
            if label and (label in needle or needle in label):
                return item

    # «сделай сводку» — то же слово в другом падеже. Сравниваем основы: без этого
    # сценарий не находился ровно тогда, когда его называли живой речью.
    from .outbox import stem

    said = {stem(word) for word in needle.split() if len(word) > 3}
    if not said:
        return None
    for item in items:
        labels = f"{item.name} {item.title}".lower().split()
        if said & {stem(word) for word in labels if len(word) > 3}:
            return item
    return None


def save(name: str, title: str, steps: Sequence[Mapping[str, Any]], say: str = "") -> Workflow:
    """Создаёт или заменяет свой сценарий."""
    clean = str(name or "").strip().lower()
    if not clean:
        raise WorkflowError("у сценария должно быть имя")
    prepared = tuple(
        Step(str(step["tool"]), dict(step.get("arguments", {})), str(step.get("note", "")))
        for step in steps if step.get("tool")
    )
    if not prepared:
        raise WorkflowError("в сценарии нет ни одного шага")

    item = Workflow(name=clean, title=str(title or name), steps=prepared, say=str(say or ""))
    with _lock:
        custom = [existing for existing in _load_custom() if existing.name != clean]
        custom.append(item)
        _save_custom(custom)
    return item


def remove(name: str) -> bool:
    clean = str(name or "").strip().lower()
    with _lock:
        custom = _load_custom()
        left = [item for item in custom if item.name != clean]
        if len(left) == len(custom):
            return False
        _save_custom(left)
    return True


# ---------------------------------------------------------------- выполнение


@dataclass
class Outcome:
    """Что получилось у сценария."""

    workflow: Workflow
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)

    def report(self) -> str:
        """Короткий честный отчёт — его и произносит Юки."""
        if not self.failed:
            head = self.workflow.say or f"{self.workflow.title}: готово."
            body = " ".join(self.results[-3:]) if self.results else ""
            return f"{head} {body}".strip()
        if not self.done:
            return f"{self.workflow.title} не выполнился: {'; '.join(self.failed[:2])}"
        return (f"{self.workflow.title}: получилось {len(self.done)} из "
                f"{len(self.done) + len(self.failed)}. Не вышло: {'; '.join(self.failed[:2])}")


def run(name: str, on_step=None) -> Outcome:
    """Выполняет сценарий шаг за шагом.

    Упавший шаг записывается и не мешает остальным: половина сценария лучше, чем
    ничего, и человеку честно говорят, какая именно половина не удалась.
    """
    from . import tools

    item = get(name)
    if item is None:
        known = ", ".join(entry.title for entry in catalog())
        raise WorkflowError(f"нет сценария «{name}». Есть: {known}")

    outcome = Outcome(workflow=item)
    deadline = time.monotonic() + STEP_LIMIT_S * max(1, len(item.steps))
    for step in item.steps:
        if time.monotonic() > deadline:
            outcome.failed.append(f"{step.describe()} — не хватило времени")
            break
        if on_step is not None:
            on_step("tool", step.describe())
        result = tools.call(step.tool, step.arguments)
        if on_step is not None:
            on_step("tool_result" if result.ok else "error", result.text[:160])
        if result.ok:
            outcome.done.append(step.describe())
            text = result.text.strip()
            if text and len(text) < 160:
                outcome.results.append(text)
        else:
            outcome.failed.append(f"{step.describe()} — {result.text[:80]}")
    return outcome
