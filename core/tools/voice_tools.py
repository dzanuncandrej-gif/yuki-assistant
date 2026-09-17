"""Инструменты голоса: список, переключение и проба.

Переключение молчаливое: подтверждение произносится уже новым голосом — им озвучивается
итоговый ответ агента. Проба (test_voice) звучит сразу и возвращает прежний голос.
"""

from __future__ import annotations

from .. import voices
from .registry import param_str, tool


@tool("list_voices", "Показывает доступные голоса ассистента и какой включён сейчас.")
def _list_voices() -> str:
    active = voices.active()
    rows = []
    for profile in voices.catalog():
        mark = " ← сейчас" if profile.key == active.key else ""
        rows.append(f"{profile.title}: {profile.character}{'' if profile.installed else ', не скачан'}{mark}")
    return "; ".join(rows)


@tool(
    "set_voice",
    "Переключает голос ассистента. Доступны: jarvis (низкий спокойный мужской), "
    "atlas (молодой естественный мужской), aura (мягкий женский).",
    {"name": param_str("Имя голоса", enum=["jarvis", "atlas", "aura"])},
    ["name"],
)
def _set_voice(name: str) -> str:
    profile = voices.apply(voices.resolve(name))
    return f"голос переключён на {profile.title} ({profile.character})"


@tool(
    "test_voice",
    "Даёт послушать, как звучит голос, не меняя выбранный.",
    {"name": param_str("Имя голоса", enum=["jarvis", "atlas", "aura"])},
    ["name"],
)
def _test_voice(name: str) -> str:
    profile = voices.resolve(name)
    voices.preview(profile)
    return f"проба голоса {profile.title} прозвучала"
