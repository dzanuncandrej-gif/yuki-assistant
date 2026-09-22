"""Набор инструментов агента. Импорт модуля регистрирует все инструменты в реестре."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import (  # noqa: F401
    app_tools,
    camera_tools,
    clock,
    file_tools,
    input_tools,
    journal_tools,
    memory_tools,
    msg_tools,
    outbox_tools,
    screen_tools,
    study_tools,
    sys_tools,
    voice_tools,
    web_tools,
    workflow_tools,
)
from .registry import (
    Result,
    Tool,
    call,
    catalog,
    get,
    names,
    pending,
    resolve_pending,
    set_request,
    specs,
)
from .routing import select

__all__ = [
    "Result",
    "Tool",
    "call",
    "catalog",
    "configure",
    "get",
    "names",
    "pending",
    "resolve_pending",
    "select",
    "set_request",
    "specs",
]


def configure(settings: Mapping[str, Any]) -> None:
    """Прокидывает настройки из config.json в те инструменты, которым они нужны."""
    file_tools.configure(str(settings.get("search_scope", "home")),
                         bool(settings.get("restrict_paths", False)))
    input_tools.configure(str(settings.get("ollama_url", "http://127.0.0.1:11434")))
    screen_tools.configure({"ollama_url": str(settings.get("ollama_url", "http://127.0.0.1:11434"))})
