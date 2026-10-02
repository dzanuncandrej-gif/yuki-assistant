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
        except Exception:
            pass
        return


def _open_video(query: str) -> str:
    video = web.youtube_video_id(query)
    _stop_own_playlist()  # две музыки разом никто не просил
    with _lock:
        _close_own_tab()
        if video:
            web.open_url(f"https://www.youtube.com/watch?v={video}&autoplay=1")
        else:
            web.open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
        _state.update(opened=True, query=query, at=time.monotonic())
    return query if video else f"{query} (открыла выдачу — ролик не нашёлся сразу)"


def stop() -> str:
    """«Выключи музыку»: свой плейлист — стоп, чужой плеер — пауза (не переключение)."""
    from . import ocr, playlist

    if playlist.active():
        return playlist.control("stop")
    try:
        reply = ocr.media("info")
        status = str((reply.get("before") or {}).get("status") or "")
    except Exception:
        status = ""
    if status and status != "Playing":
        return "уже тихо"
    automation.media("play_pause")
    return "выключила"


def _stop_own_playlist() -> None:
    from . import playlist

    if playlist.active():
        playlist.control("stop")


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


def _title(info: dict) -> str:
    title = str(info.get("title") or "").strip()
    artist = str(info.get("artist") or "").strip()
    return f"{artist} — {title}" if artist and title and artist not in title else title


def control(action: str) -> str:
    """Следующий / предыдущий / пауза — через медиасессию Windows, с проверкой.

    Раньше здесь вслепую нажималась медиаклавиша, а ответ всегда был
    «переключила» — даже когда ничего не играло или плеер клавишу не принял.
    Теперь команда идёт той программе, что играет (браузер с YouTube, Spotify,
    Яндекс Музыка), и сверяется название до и после.
    """
    from . import ocr, playlist

    if playlist.active():
        return playlist.control(action)
    try:
        reply = ocr.media(action)
    except Exception:
        reply = {}
    if reply.get("ok") is False and reply.get("error") == "nothing":
        raise automation.ActionError("сейчас ничего не играет — нечего переключать")
    if not reply.get("ok"):
        # медиасессии недоступны — старый путь: медиаклавиша
        automation.media({"previous": "prev"}.get(action, action))
        return "нажала медиаклавишу"
    before, after = reply.get("before") or {}, reply.get("after") or {}
    if action in ("next", "previous"):
        if _title(after) and _title(after) != _title(before):
            return f"включила «{_title(after)}»"
        if not reply.get("done"):
            # плеер отказался от «следующего» (так бывает с одиночным видео на YouTube)
            automation.press_hotkey(("shift", "n"))
            return "переключила на следующее видео"
        return "переключила"
    if action == "play_pause":
        return "поставила на паузу" if str(after.get("status")) == "Paused" else "продолжила"
    return _title(after) or "готово"


def next_track() -> str:
    """Следующий трек или ролик — с проверкой, что он правда сменился."""
    return control("next")


def now_playing() -> str:
    """Что сейчас играет, если что-то играет."""
    from . import ocr, playlist

    own = playlist.now_playing()
    if own is not None:
        return own.label

    try:
        reply = ocr.media("info")
    except Exception:
        return ""
    return _title(reply.get("before") or {}) if reply.get("ok") else ""


def last_query() -> str:
    return str(_state["query"] or "")


_NOISE = re.compile(
    r"\s*[\(\[](?:official|офиц|music\s+video|lyric|audio|video|клип|hd|4k|live|remaster)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def playing_info() -> dict[str, str]:
    """Что играет сейчас: исполнитель и название. Пусто — ничего не играет.

    Берётся из медиасессии Windows: её заполняет любой плеер, и YouTube в
    браузере тоже. У YouTube в «исполнителе» часто канал, а настоящий артист —
    в названии ролика «Артист - Песня», поэтому название разбирается отдельно.
    """
    from . import ocr, playlist

    own = playlist.now_playing()
    if own is not None:
        return {"artist": own.artist, "song": own.title, "app": "Юки"}
    try:
        reply = ocr.media("info")
    except Exception:
        reply = {}
    info = reply.get("before") or {} if reply.get("ok") else {}
    title = _NOISE.sub("", str(info.get("title") or "")).strip()
    artist = str(info.get("artist") or "").strip()
    if not title and _state.get("query"):
        title = str(_state["query"])
    if not title:
        return {}
    song = title
    for dash in (" — ", " – ", " - "):
        if dash in title:
            left, right = title.split(dash, 1)
            artist, song = left.strip(), right.strip()
            break
    artist = re.sub(r"\s*(?:-\s*topic|VEVO|official)$", "", artist, flags=re.IGNORECASE).strip()
    return {"artist": artist, "song": song, "app": str(info.get("app") or "")}
