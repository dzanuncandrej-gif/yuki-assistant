"""Защита Windows от «чужого» ввода и перезапуск Юки от администратора.

Окно, запущенное от администратора (диспетчер задач, установщик, часть игр и
античитов), не принимает клавиатуру и мышь от обычного процесса — так работает
UIPI. Коварство в том, что SendInput при этом рапортует об успехе: события
«ушли», но окно их молча выбросило. Раньше Юки в такой ситуации говорила
«нажала», а на экране ничего не менялось.

Здесь это видно заранее: перед вводом проверяем, не выше ли права целевого окна,
и если выше — честно говорим, в чём дело, и предлагаем перезапуск с правами.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
GA_ROOT = 2
_CACHE_S = 2.0

_cache: dict[int, tuple[float, bool]] = {}


def _win() -> bool:
    return sys.platform == "win32"


def is_admin() -> bool:
    """Запущены ли мы сами с правами администратора."""
    if not _win():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _process_elevated(pid: int) -> bool:
    """Повышены ли права у процесса. Отказ в доступе тоже считаем повышенными:
    так отвечают защищённые и административные процессы, и ввод они не примут."""
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return True
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return True
        try:
            elevation = wintypes.DWORD()
            size = wintypes.DWORD()
            ok = advapi32.GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(elevation),
                                              ctypes.sizeof(elevation), ctypes.byref(size))
            return bool(ok) and bool(elevation.value)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(handle)


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _window_title(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value.strip()


def window_blocked(hwnd: int | None) -> str | None:
    """Название окна, если Windows не пустит в него наш ввод, иначе None."""
    if not _win() or not hwnd or is_admin():
        return None
    try:
        pid = _window_pid(hwnd)
        if not pid or pid == os.getpid():
            return None
        now = time.monotonic()
        cached = _cache.get(pid)
        if cached is not None and now - cached[0] < _CACHE_S:
            elevated = cached[1]
        else:
            elevated = _process_elevated(pid)
            _cache[pid] = (now, elevated)
        if not elevated:
            return None
        return _window_title(hwnd) or "окно с правами администратора"
    except (OSError, AttributeError):
        return None


def foreground_blocked() -> str | None:
    if not _win():
        return None
    return window_blocked(int(ctypes.windll.user32.GetForegroundWindow() or 0))


def point_blocked(x: int, y: int) -> str | None:
    """То же для окна под точкой — туда придёт щелчок мыши."""
    if not _win():
        return None
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    root = user32.GetAncestor(hwnd, GA_ROOT) if hwnd else None
    return window_blocked(int(root or hwnd or 0))


def blocked_message(title: str) -> str:
    return (f"окно «{title}» запущено от имени администратора, и Windows не пускает в него "
            "ввод от обычной программы. Скажи «перезапустись от администратора» — "
            "и я смогу управлять и такими окнами")


def relaunch_as_admin() -> bool:
    """Запускает Юки заново с правами администратора (Windows спросит согласие).

    True — новый экземпляр запрошен; текущему остаётся закрыться самому.
    """
    if not _win():
        return False
    executable = Path(sys.executable)
    # без консоли: pythonw рядом с python, если он есть
    windowed = executable.with_name("pythonw.exe")
    if windowed.is_file():
        executable = windowed
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else Path("main.py").resolve()
    arguments = " ".join(f'"{item}"' for item in [str(script), *sys.argv[1:]])
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(executable), arguments, str(script.parent), 1
    )
    return int(result) > 32
