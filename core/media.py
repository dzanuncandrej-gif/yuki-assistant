"""Музыка и видео через YouTube в браузере — без ключей и без отдельного плеера.

Главное правило: одновременно играет что-то одно. Раньше каждая просьба «включи
другую песню» открывала новую вкладку, а старая продолжала звучать — получалась
каша из двух треков. Теперь вкладка, открытая прошлой просьбой, закрывается перед
тем, как открыть новую. Чужие вкладки YouTube (которые человек открыл сам) не
трогаются: закрывается только то, что включила сама Юки.
"""

from __future__ import annotations

import re
import threading
import time
from urllib.parse import quote_plus

from . import automation, web
from . import windows as win

BROWSER_PROCESSES = (
    "chrome.exe", "msedge.exe", "browser.exe", "firefox.exe", "opera.exe",
    "brave.exe", "vivaldi.exe", "yandex.exe",
)

# что включать, если попросили «просто музыку»
DEFAULT_MUSIC_QUERY = "популярные хиты плейлист"

# слова-заглушки: «включи какую-нибудь музыку» — это не название трека
_VAGUE = re.compile(
    r"^(?:мне\s+)?(?:какую[\s-]*(?:нибудь|то)|любую|что[\s-]*нибудь|что[\s-]*то|немного|"
    r"хорошую|классную|нормальную)?\s*(?:музыку|музыка|музон|песню|песни|песенку|трек|треки)?$",
    re.IGNORECASE,
)

_state: dict[str, object] = {"opened": False, "query": "", "at": 0.0}
_lock = threading.Lock()


def is_vague(query: str | None) -> bool:
    """Попросили музыку вообще, без названия."""
    return bool(_VAGUE.match((query or "").strip()))


def _close_own_tab() -> None:
    """Закрывает вкладку YouTube, которую открыла прошлая просьба.

    Заголовок окна браузера — это заголовок активной вкладки. Если там YouTube и
    вкладку открывали мы, Ctrl+W закрывает именно её. Любая неудача здесь не
    мешает включить новое: лучше два трека, чем ни одного.
    """
    if not _state["opened"]:
        return
    for window in win.enumerate_windows():
        if window.process.lower() not in BROWSER_PROCESSES or "youtube" not in window.title.lower():
            continue
        try:
            win.focus(window)
            time.sleep(0.35)
            active = win.active_window()
            if active is not None and active.hwnd == window.hwnd and "youtube" in active.title.lower():
                automation.press_hotkey(("ctrl", "w"))
                time.sleep(0.3)
        except Exception:  # noqa: BLE001 — закрыть не вышло, новое всё равно включаем
            pass
        return


def _open_video(query: str) -> str:
    video = web.youtube_video_id(query)
    with _lock:
        _close_own_tab()
        if video:
            web.open_url(f"https://www.youtube.com/watch?v={video}&autoplay=1")
        else:
            web.open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
        _state.update(opened=True, query=query, at=time.monotonic())
    return query if video else f"{query} (открыла выдачу — ролик не нашёлся сразу)"


def play_music(query: str | None = None) -> str:
    """Включает трек, исполнителя или жанр. Возвращает, что включено."""
    request = (query or "").strip(" .,!?")
    if is_vague(request):
        request = DEFAULT_MUSIC_QUERY
    return _open_video(request)


def play_video(query: str) -> str:
    """Включает первый подходящий ролик."""
    request = (query or "").strip(" .,!?")
    if not request:
        raise web.WebError("не сказано, какое видео включить")
    return _open_video(request)


def search_youtube(query: str) -> str:
    """Открывает выдачу YouTube — когда человек хочет выбрать сам."""
    request = (query or "").strip(" .,!?")
    if not request:
        raise web.WebError("не сказано, что искать на YouTube")
    web.open_url(f"https://www.youtube.com/results?search_query={quote_plus(request)}")
    return request


def next_track() -> str:
    """Следующий трек: YouTube принимает медиаклавишу и переходит к следующему ролику."""
    automation.media("next")
    return "следующий"


def last_query() -> str:
    return str(_state["query"] or "")
