"""Работа с окнами Windows: перечисление, поиск, свернуть/развернуть/закрыть, контекст экрана."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

import psutil
import win32con
import win32gui
import win32process

# окна-служебки, которые не интересны пользователю
_SKIP_TITLES = frozenset(
    {
        "program manager", "windows input experience", "settings", "microsoft text input application",
        "nvidia geforce overlay", "default ime", "msctfime ui",
    }
)


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process: str

    @property
    def label(self) -> str:
        return self.title or self.process


class WindowError(RuntimeError):
    """Окно не найдено или действие не применимо."""


def _process_name(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return ""


def enumerate_windows() -> tuple[WindowInfo, ...]:
    """Видимые окна верхнего уровня с заголовком."""
    found: list[WindowInfo] = []

    def collect(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title or title.lower() in _SKIP_TITLES:
            return
        if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
            return
        found.append(WindowInfo(hwnd, title, _process_name(hwnd)))

    win32gui.EnumWindows(collect, None)
    return tuple(found)


def active_window() -> WindowInfo | None:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    return WindowInfo(hwnd, win32gui.GetWindowText(hwnd).strip(), _process_name(hwnd))


def find(query: str) -> WindowInfo:
    """Ищет окно по заголовку или имени процесса: подстрока, затем нечёткое совпадение."""
    needle = query.strip().lower()
    if not needle:
        raise WindowError("не понял, какое окно")
    windows = enumerate_windows()
    if not windows:
        raise WindowError("нет открытых окон")

    for window in windows:
        haystack = f"{window.title} {window.process}".lower()
        if needle in haystack:
            return window

    titles = {window.title.lower(): window for window in windows}
    close = difflib.get_close_matches(needle, tuple(titles), n=1, cutoff=0.55)
    if close:
        return titles[close[0]]
    raise WindowError(f"окно «{query}» не найдено")


def rect(window: WindowInfo) -> tuple[int, int, int, int]:
    """Границы окна (left, top, right, bottom) — нужны для кликов по элементам интерфейса."""
    try:
        return tuple(int(value) for value in win32gui.GetWindowRect(window.hwnd))  # type: ignore[return-value]
    except Exception as err:
        raise WindowError(f"не удалось получить размеры окна «{window.label}»") from err


def _show(window: WindowInfo, command: int) -> None:
    win32gui.ShowWindow(window.hwnd, command)


def minimize(window: WindowInfo) -> str:
    _show(window, win32con.SW_MINIMIZE)
    return window.label


def maximize(window: WindowInfo) -> str:
    _show(window, win32con.SW_MAXIMIZE)
    return window.label


def restore(window: WindowInfo) -> str:
    _show(window, win32con.SW_RESTORE)
    return window.label


def close(window: WindowInfo) -> str:
    win32gui.PostMessage(window.hwnd, win32con.WM_CLOSE, 0, 0)
    return window.label


def _unfold(hwnd: int) -> None:
    """Разворачивает свёрнутое окно, не трогая уже развёрнутое на весь экран."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    else:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)


def _attach_and_activate(hwnd: int) -> None:
    """Обходит блокировку смены фокуса: подключаемся к потоку активного окна.

    Windows разрешает менять передний план только процессу, который уже владеет фокусом.
    Без этого SetForegroundWindow «срабатывает» молча, окно всплывает, но клавиатура
    остаётся у прежнего приложения — и текст уходит не туда.
    """
    import ctypes

    user32 = ctypes.windll.user32
    current = user32.GetForegroundWindow()
    target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
    source_thread = win32process.GetWindowThreadProcessId(current)[0] if current else 0
    own_thread = ctypes.windll.kernel32.GetCurrentThreadId()

    attached = []
    for thread in {source_thread, own_thread}:
        if thread and thread != target_thread and user32.AttachThreadInput(thread, target_thread, True):
            attached.append(thread)
    try:
        # короткий Alt снимает блокировку активации из фонового процесса
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        win32gui.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for thread in attached:
            user32.AttachThreadInput(thread, target_thread, False)


def focus(window: WindowInfo, timeout_s: float = 2.0) -> str:
    """Делает окно активным по-настоящему: проверяет, что оно стало передним."""
    import time

    _unfold(window.hwnd)
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while time.monotonic() < deadline:
        try:
            _attach_and_activate(window.hwnd)
        except Exception:
            pass
        time.sleep(0.15)
        if win32gui.GetForegroundWindow() == window.hwnd:
            return window.label
        attempt += 1
        if attempt == 2:
            try:
                win32gui.SetWindowPos(
                    window.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
                )
                win32gui.SetWindowPos(
                    window.hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
                )
            except Exception:
                pass
    if win32gui.GetForegroundWindow() != window.hwnd:
        raise WindowError(f"окно «{window.label}» не получило фокус — ввод ушёл бы не туда")
    return window.label


def minimize_active() -> str:
    window = active_window()
    if window is None:
        raise WindowError("нет активного окна")
    return minimize(window)


def maximize_active() -> str:
    window = active_window()
    if window is None:
        raise WindowError("нет активного окна")
    return maximize(window)


def close_active() -> str:
    window = active_window()
    if window is None:
        raise WindowError("нет активного окна")
    return close(window)


def screen_context(limit: int = 6) -> str:
    """Что сейчас на экране: активное окно плюс остальные открытые."""
    current = active_window()
    windows = [w for w in enumerate_windows() if current is None or w.hwnd != current.hwnd]
    parts = []
    if current is not None and current.label:
        parts.append(f"Активно окно «{current.label}»")
    if windows:
        names = ", ".join(w.label for w in windows[:limit])
        parts.append(f"также открыты: {names}")
    return ". ".join(parts) if parts else "На экране нет открытых окон."
