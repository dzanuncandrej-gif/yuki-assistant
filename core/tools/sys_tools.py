"""Инструменты системы: звук, медиа, яркость, буфер обмена, питание, оболочка, статистика."""

from __future__ import annotations

import re

from .. import automation
from .registry import param_int, param_str, tool

# команды, которые нельзя выполнять без явного согласия человека
_DANGEROUS = re.compile(
    r"(format\s+[a-z]:|del\s+/[sq]\s|rd\s+/s\s|remove-item[^|]*-recurse[^|]*(c:\\|\\windows)|"
    r"diskpart|bcdedit|vssadmin\s+delete|cipher\s+/w|reg\s+delete\s+hklm)",
    re.IGNORECASE,
)


@tool(
    "volume_set",
    "Ставит громкость системы в процентах (0-100).",
    {"level": param_int("Громкость 0..100")},
    ["level"],
)
def _volume_set(level: int) -> str:
    from .. import journal

    try:
        previous = automation.volume_get()
    except Exception:
        previous = None
    value = automation.volume_set(level)
    if previous is not None:
        journal.record(
            f"громкость {previous} → {value}",
            undo=lambda: f"вернул громкость {automation.volume_set(previous)}",
        )
    return f"громкость {value} процентов"


@tool(
    "volume_change",
    "Меняет громкость на указанное число процентов: положительное — громче, отрицательное — тише.",
    {"delta": param_int("На сколько процентов изменить, например 10 или -15")},
    ["delta"],
)
def _volume_change(delta: int) -> str:
    value = automation.volume_step(int(delta))
    return f"громкость {value} процентов" if value >= 0 else "громкость изменена"


@tool("volume_get", "Текущая громкость системы в процентах.")
def _volume_get() -> str:
    return f"громкость {automation.volume_get()} процентов"


@tool("mute_toggle", "Включает или выключает звук полностью.")
def _mute() -> str:
    return f"звук {automation.mute_toggle()}"


@tool(
    "media_control",
    "Управление плеером: воспроизведение/пауза, следующий или предыдущий трек.",
    {"action": param_str("Одно из: play_pause, next, prev, stop", enum=["play_pause", "next", "prev", "stop"])},
    ["action"],
)
def _media(action: str) -> str:
    key = action.strip().lower()
    if key not in ("play_pause", "next", "prev", "stop"):
        raise ValueError("допустимо: play_pause, next, prev, stop")
    automation.media(key)
    return f"медиа: {key}"


@tool(
    "brightness_set",
    "Ставит яркость монитора в процентах (0-100).",
    {"level": param_int("Яркость 0..100")},
    ["level"],
)
def _brightness(level: int) -> str:
    from .. import journal

    try:
        previous = automation.brightness_get()
    except Exception:
        previous = None
    value = automation.brightness_set(level)
    if previous is not None:
        journal.record(
            f"яркость {previous} → {value}",
            undo=lambda: f"вернул яркость {automation.brightness_set(previous)}",
        )
    return f"яркость {value} процентов"


@tool("brightness_get", "Текущая яркость монитора.")
def _brightness_get() -> str:
    return f"яркость {automation.brightness_get()} процентов"


@tool("clipboard_get", "Читает текст из буфера обмена.")
def _clipboard_get() -> str:
    content = automation.get_clipboard()
    return f"в буфере: {content[:800]}" if content else "буфер обмена пуст"


@tool(
    "clipboard_set",
    "Кладёт текст в буфер обмена.",
    {"text": param_str("Текст для буфера")},
    ["text"],
)
def _clipboard_set(text: str) -> str:
    automation.set_clipboard(text)
    return "текст в буфере обмена"


@tool("system_stats", "Загрузка процессора, памяти, дисков, состояние батареи и время работы.")
def _stats() -> str:
    return automation.system_stats()


@tool(
    "run_shell",
    "Выполняет команду PowerShell/CMD и возвращает вывод. Универсальный запасной путь, "
    "когда специализированного инструмента нет: сетевые настройки, службы, процессы, реестр.",
    {
        "command": param_str("Команда оболочки Windows"),
        "timeout": param_int("Ограничение по времени в секундах, по умолчанию 20"),
    },
    ["command"],
    confirm=True,
)
def _run_shell(command: str, timeout: int = 20) -> str:
    if _DANGEROUS.search(command):
        raise PermissionError(
            "команда выглядит разрушительной (форматирование, удаление системных данных). "
            "Нужно явное подтверждение пользователя голосом"
        )
    return automation.run_command(command, timeout_s=float(max(2, min(120, timeout))))


@tool(
    "kill_process",
    "Принудительно завершает процесс по имени, если приложение зависло.",
    {"name": param_str("Имя процесса, например chrome")},
    ["name"],
)
def _kill(name: str) -> str:
    from .app_tools import _CLOSE_WORDS, _need_intent

    _need_intent(_CLOSE_WORDS, "завершить процесс")
    return f"завершено: {automation.kill_process(name)}"


@tool("lock_computer", "Блокирует компьютер (экран блокировки Windows).")
def _lock() -> str:
    automation.lock_workstation()
    return "компьютер заблокирован"


@tool(
    "power_control",
    "Выключение, перезагрузка, выход из системы, гибернация или сон. Действие необратимо: "
    "выполняется с задержкой, её можно отменить действием cancel.",
    {
        "action": param_str(
            "Одно из: shutdown, restart, logoff, hibernate, sleep, cancel",
            enum=["shutdown", "restart", "logoff", "hibernate", "sleep", "cancel"],
        ),
    },
    ["action"],
    confirm=True,
)
def _power(action: str) -> str:
    key = action.strip().lower()
    if key == "cancel":
        automation.power_cancel()
        return "выключение отменено"
    if key == "sleep":
        automation.sleep_pc()
        return "компьютер уходит в сон"
    delay = automation.power(key)
    return f"{key} через {delay} секунд, можно отменить" if delay else f"{key} выполняется"


@tool(
    "network_adapter",
    "Включает или выключает сетевой адаптер Wi-Fi. Требует прав администратора.",
    {
        "enable": param_str("on или off", enum=["on", "off"]),
        "name": param_str("Имя адаптера, по умолчанию Wi-Fi"),
    },
    ["enable"],
)
def _network(enable: str, name: str = "Wi-Fi") -> str:
    state = enable.strip().lower() in ("on", "true", "да", "1")
    return f"адаптер {automation.network_adapter(state, name)} {'включён' if state else 'выключен'}"


@tool("empty_recycle_bin", "Очищает корзину Windows.", confirm=True)
def _recycle() -> str:
    automation.empty_recycle_bin()
    return "корзина очищена"
