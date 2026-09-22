"""Границы безопасности агента.

Эти проверки закрывают замечания внешнего обзора безопасности: необратимые
инструменты не должны выполняться с первого вызова модели, файловые операции
должны уметь запираться в домашней папке, а нейроголос по сети — не включаться
сам по себе.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.tools import file_tools, registry

# Инструменты, которые меняют систему необратимо или запускают чужой код.
MUST_CONFIRM = (
    "run_shell",
    "write_file",
    "delete_path",
    "power_control",
    "empty_recycle_bin",
)


@pytest.mark.parametrize("name", MUST_CONFIRM)
def test_dangerous_tools_require_confirmation(name: str) -> None:
    tool = registry.get(name)
    assert tool is not None, f"инструмент {name} пропал из реестра"
    assert tool.confirm is True, f"{name} выполняется без подтверждения человека"


def test_confirmation_is_not_bypassed_by_first_call() -> None:
    """Первый вызов необратимого инструмента обязан вернуть вопрос, а не результат."""
    registry.clear_pending()
    result = registry.call("power_control", {"action": "shutdown"})
    assert "ПОДТВЕРЖДЕНИЕ" in result.text.upper()
    registry.clear_pending()


def test_restricted_paths_block_outside_home() -> None:
    file_tools.configure("home", True)
    try:
        with pytest.raises(PermissionError):
            file_tools.resolve(r"C:\Windows\System32\drivers\etc\hosts")
    finally:
        file_tools.configure("home", False)


def test_restricted_paths_allow_home_and_relative() -> None:
    file_tools.configure("home", True)
    try:
        inside = file_tools.resolve(str(Path.home() / "Desktop" / "отчёт.txt"))
        assert Path.home() in inside.parents
        assert file_tools.resolve("рабочий стол/отчёт.txt").name == "отчёт.txt"
    finally:
        file_tools.configure("home", False)


def test_unrestricted_mode_keeps_previous_behaviour() -> None:
    file_tools.configure("home", False)
    assert file_tools.resolve(r"C:\Windows\notepad.exe").as_posix().endswith("notepad.exe")


def test_cloud_voice_is_opt_in() -> None:
    """Edge-TTS уводит текст ответа в сеть — сам по себе включаться не должен."""
    from core import tts

    allowed = tts.Speaker._edge_allowed

    assert allowed(_FakeSpeaker({"engine": "auto"})) is False
    assert allowed(_FakeSpeaker({"engine": "auto", "allow_cloud_voice": True})) is True
    assert allowed(_FakeSpeaker({"engine": "edge"})) is True


class _FakeSpeaker:
    """Достаточно для проверки решения о сети: настоящий синтез тут не нужен."""

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
