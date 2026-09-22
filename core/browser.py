"""Управление браузером: открытие адресов, ввод в адресную строку, чтение текста страницы.

Работает с уже установленным браузером пользователя (Chrome, Edge, Yandex, Firefox, Opera):
адрес открывается штатным способом, дальше — обычные горячие клавиши, как у человека.
"""

from __future__ import annotations

import time
import webbrowser
from urllib.parse import quote_plus

from . import automation
from . import windows as win

BROWSER_PROCESSES = (
    "chrome.exe", "msedge.exe", "browser.exe", "firefox.exe", "opera.exe",
    "brave.exe", "vivaldi.exe", "yandex.exe",
)

SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={}",
    "yandex": "https://yandex.ru/search/?text={}",
    "duckduckgo": "https://duckduckgo.com/?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
}


class BrowserError(RuntimeError):
    """Браузер не найден или страница не открылась."""


def _normalize(url: str) -> str:
    clean = url.strip()
    if clean.startswith(("http://", "https://", "file://")):
        return clean
    if " " in clean or "." not in clean:
        return SEARCH_ENGINES["google"].format(quote_plus(clean))
    return f"https://{clean}"


def browser_window(timeout_s: float = 12.0):
    """Ждёт появления окна браузера и возвращает его."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for window in win.enumerate_windows():
            if window.process.lower() in BROWSER_PROCESSES:
                return window
        time.sleep(0.3)
    raise BrowserError("окно браузера не найдено")


def focus() -> str:
    """Выводит браузер на передний план — следующая команда попадёт в него."""
    window = browser_window()
    win.focus(window)
    time.sleep(0.4)
    return window.title


def open_url(url: str, timeout_s: float = 15.0) -> str:
    """Открывает адрес и убеждается, что окно браузера действительно появилось."""
    target = _normalize(url)
    webbrowser.open(target)
    window = browser_window(timeout_s)
    try:
        win.focus(window)
    except win.WindowError:
        pass
    time.sleep(0.8)
    current = win.active_window()
    return (current.title if current is not None else window.title) or target


def search(query: str, engine: str = "google") -> str:
    """Открывает поисковую выдачу в браузере."""
    template = SEARCH_ENGINES.get(engine.lower(), SEARCH_ENGINES["google"])
    return open_url(template.format(quote_plus(query.strip())))


def go_to(url: str) -> str:
    """Переход в уже открытом браузере через адресную строку."""
    focus()
    automation.press_hotkey(("ctrl", "l"))
    time.sleep(0.2)
    automation.type_text(_normalize(url))
    time.sleep(0.1)
    automation.press_hotkey(("enter",))
    time.sleep(1.5)
    current = win.active_window()
    return current.title if current is not None else url


def page_text(limit: int = 4000) -> str:
    """Текст открытой вкладки через выделение и копирование."""
    focus()
    previous = automation.get_clipboard()
    automation.set_clipboard("")
    automation.press_hotkey(("ctrl", "a"))
    time.sleep(0.2)
    automation.press_hotkey(("ctrl", "c"))
    time.sleep(0.5)
    text = (automation.get_clipboard() or "").strip()
    automation.press_hotkey(("esc",))
    if previous:
        automation.set_clipboard(previous)
    if not text:
        raise BrowserError("не удалось скопировать текст страницы")
    return text[:limit]


def find_on_page(needle: str) -> str:
    focus()
    automation.press_hotkey(("ctrl", "f"))
    time.sleep(0.2)
    automation.type_text(needle)
    time.sleep(0.4)
    automation.press_hotkey(("enter",))
    time.sleep(0.2)
    automation.press_hotkey(("esc",))
    return needle


def new_tab(url: str | None = None) -> str:
    focus()
    automation.press_hotkey(("ctrl", "t"))
    time.sleep(0.4)
    if url:
        automation.type_text(_normalize(url))
        automation.press_hotkey(("enter",))
        time.sleep(1.5)
    current = win.active_window()
    return current.title if current is not None else "новая вкладка"


def close_tab() -> str:
    focus()
    automation.press_hotkey(("ctrl", "w"))
    time.sleep(0.3)
    return "вкладка закрыта"


def back() -> str:
    focus()
    automation.press_hotkey(("alt", "left"))
    time.sleep(0.6)
    current = win.active_window()
    return current.title if current is not None else "назад"


def scroll(amount: int = -600) -> str:
    """Прокрутка страницы: отрицательное значение — вниз."""
    focus()
    automation.scroll(amount)
    return f"прокрутил на {amount}"
