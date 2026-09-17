"""Инструменты сценариев: показать, что есть, и выполнить по имени."""

from __future__ import annotations

from .. import workflows
from .registry import param_str, tool


@tool(
    "list_workflows",
    "Какие сценарии настроены: «рабочий режим», «отдых», «сводка» и свои. "
    "Сценарий — это несколько действий под одним именем.",
)
def _list_workflows() -> str:
    items = workflows.catalog()
    if not items:
        return "сценариев пока нет"
    return "; ".join(f"«{item.title}» — {len(item.steps)} шага" for item in items)


@tool(
    "run_workflow",
    "Выполняет сценарий по названию: «рабочий режим», «отдых», «закончить работу». "
    "Вызывай, когда человек называет режим или распорядок, а не одно действие.",
    {"name": param_str("Название сценария")},
    ["name"],
)
def _run_workflow(name: str) -> str:
    outcome = workflows.run(name)
    return outcome.report()
