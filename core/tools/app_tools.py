"""Инструменты приложений и окон. Каждый запуск проверяется: появилось окно или процесс."""

from __future__ import annotations

import time

import psutil

from .. import apps
from .. import windows as win
from .registry import param_str, request_mentions, tool

# слова, без которых закрытие окон и программ не выполняется: так модель не «наводит
# порядок» по своей инициативе, услышав обрывок постороннего разговора
_CLOSE_WORDS = (
    "закр", "заверш", "выключ", "убей", "сними", "останов", "выйди", "close", "quit", "kill", "exit",
)


def _need_intent(words: tuple[str, ...], action: str) -> None:
    if not request_mentions(words):
        raise PermissionError(f"в просьбе не было «{action}» — действие не выполняю")


def _process_running(name: str) -> str | None:
    needle = name.strip().lower().removesuffix(".exe")
    if not needle:
        return None
    for process in psutil.process_iter(["name"]):
        current = str(process.info.get("name") or "").lower()
        if current and needle in current.removesuffix(".exe"):
            return current
    return None


@tool(
    "open_app",
    "Запускает программу или игру по названию (телеграм, chrome, блокнот, steam, кс2) и "
    "выводит её окно вперёд. Проверяет, что приложение действительно открылось.",
    {"name": param_str("Название приложения так, как его называет человек")},
    ["name"],
)
def _open_app(name: str) -> str:
    launched = apps.launch(name)
    window = apps.wait_for_window(launched, timeout_s=12.0)
    if window is not None:
        try:
            win.focus(window)
        except win.WindowError:
            pass
        time.sleep(0.4)
        return f"«{launched}» запущено, активно окно «{window.title}»"

    process = _process_running(launched)
    if process:
        return f"«{launched}» запущено (процесс {process}), окно ещё не появилось"
    time.sleep(2.0)
    if _process_running(launched):
        return f"«{launched}» запускается"
    raise RuntimeError(f"«{launched}» не запустилось: окна и процесса нет")


@tool(
    "close_app",
    "Закрывает приложение по названию: сначала аккуратно окно, затем процесс.",
    {"name": param_str("Название приложения")},
    ["name"],
)
def _close_app(name: str) -> str:
    _need_intent(_CLOSE_WORDS, "закрыть приложение")
    closed = apps.close(name)
    time.sleep(1.0)
    still = _process_running(name)
    return f"закрыто: {closed}" + (f" (процесс {still} ещё завершается)" if still else "")


@tool("list_windows", "Список открытых окон с названиями — что сейчас на экране.")
def _list_windows() -> str:
    windows = win.enumerate_windows()
    if not windows:
        return "открытых окон нет"
    active = win.active_window()
    rows = [f"«{item.title}» ({item.process})" for item in windows[:12]]
    head = f"активно «{active.title}». " if active is not None else ""
    return head + "открыты: " + "; ".join(rows)


@tool(
    "focus_window",
    "Переключается на окно по части названия или имени процесса — чтобы печатать именно туда.",
    {"name": param_str("Часть заголовка окна или имя программы")},
    ["name"],
)
def _focus(name: str) -> str:
    window = win.find(name)
    win.focus(window)
    time.sleep(0.3)
    current = win.active_window()
    if current is not None and current.hwnd == window.hwnd:
        return f"активно окно «{window.title}»"
    return f"окно «{window.title}» поднято, но фокус удержало «{current.title if current else '—'}»"


@tool(
    "window_control",
    "Свернуть, развернуть, восстановить или закрыть окно. Без имени действует на активное окно.",
    {
        "action": param_str(
            "Одно из: minimize, maximize, restore, close, minimize_all",
            enum=["minimize", "maximize", "restore", "close", "minimize_all"],
        ),
        "name": param_str("Часть заголовка окна; пусто — активное окно"),
    },
    ["action"],
)
def _window_control(action: str, name: str = "") -> str:
    from .. import automation

    key = action.strip().lower()
    if key == "close":
        # проверяем намерение до поиска окна: иначе отказ теряется за «окно не найдено»
        _need_intent(_CLOSE_WORDS, "закрыть окно")
    if key == "minimize_all":
        automation.minimize_all()
        return "все окна свёрнуты"

    window = win.find(name) if name.strip() else win.active_window()
    if window is None:
        raise RuntimeError("нет активного окна")

    handlers = {
        "minimize": win.minimize,
        "maximize": win.maximize,
        "restore": win.restore,
        "close": win.close,
    }
    handler = handlers.get(key)
    if handler is None:
        raise ValueError("допустимо: minimize, maximize, restore, close, minimize_all")
    label = handler(window)
    return f"{key}: «{label}»"


@tool("running_apps", "Какие программы сейчас запущены и видны пользователю.")
def _running() -> str:
    items = apps.running(limit=10)
    return "запущены: " + ", ".join(items) if items else "видимых окон нет"
