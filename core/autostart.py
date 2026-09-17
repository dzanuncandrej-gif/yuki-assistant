"""Запуск Юки вместе с Windows.

Используется пользовательская ветка реестра `HKCU\\...\\Run`: она не требует
прав администратора, видна в диспетчере задач на вкладке «Автозагрузка» и
снимается оттуда штатными средствами, а не только через это приложение.

Команда запуска собирается из текущего интерпретатора. Если рядом есть
`pythonw.exe`, берётся он — иначе при каждом входе в систему открывалось бы
чёрное окно консоли.
"""

from __future__ import annotations

import sys
from pathlib import Path

KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "Jarvis"

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "main.py"


def supported() -> bool:
    return sys.platform == "win32"


def _interpreter() -> Path:
    """Интерпретатор без консольного окна, если такой есть рядом."""
    current = Path(sys.executable)
    quiet = current.with_name("pythonw.exe")
    return quiet if quiet.is_file() else current


def command() -> str:
    return f'"{_interpreter()}" "{ENTRY}"'


def enabled() -> bool:
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            value, _ = winreg.QueryValueEx(key, NAME)
    except OSError:
        return False
    return str(value).strip() == command()


def set_enabled(enable: bool) -> bool:
    """Включает или выключает автозапуск. Возвращает получившееся состояние."""
    if not supported():
        return False
    import winreg

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(key, NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        return enabled()
    return enable


def sync(desired: bool) -> bool:
    """Приводит реестр в согласие с настройкой. Лишних записей не делает."""
    if not supported() or desired == enabled():
        return enabled()
    return set_enabled(desired)
