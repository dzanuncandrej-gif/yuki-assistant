"""Встроенная веб-страница интерфейса: пульт диалога и окно звонка.

Страница читается с диска по внутренней схеме `jarvis:` (см. webassets), а
разговаривает с питоном по QWebChannel. Сети, портов и внешнего браузера нет.
Если QtWebEngine недоступен, `ENGINE_READY` ложно и вызывающий берёт прежний
интерфейс на обычных виджетах.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor

from . import webassets

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    ENGINE_READY = True
except ImportError:  # pragma: no cover — сборка без QtWebEngine
    ENGINE_READY = False

# события, которые странице не нужны: их много, а показать нечего
_SKIP_EVENTS = frozenset({"viseme", "emotion"})


def build_view(page_name: str, link: QObject, parent=None, background: str = "#03050b") -> QWebEngineView:
    """Собирает QWebEngineView со своей схемой и каналом `yuki` → link."""
    view = QWebEngineView(parent)
    profile = QWebEngineProfile(f"yuki-{page_name}", view)
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    handler = webassets.AssetHandler(parent=profile)
    profile.installUrlSchemeHandler(webassets.SCHEME, handler)
    view._asset_handler = handler  # держим ссылку: без неё обработчик соберёт сборщик мусора

    page = QWebEnginePage(profile, view)
    page.setBackgroundColor(QColor(background))
    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)

    channel = QWebChannel(page)
    channel.registerObject("yuki", link)
    page.setWebChannel(channel)

    view.setPage(page)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    view.load(webassets.url(page_name))
    return view


def event_json(payload: dict[str, Any]) -> str | None:
    """Событие шины строкой JSON, или None, если странице оно не нужно."""
    if payload.get("type") in _SKIP_EVENTS:
        return None
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None


def system_load() -> tuple[float, float]:
    """Загрузка процессора и памяти в процентах; нули, если psutil нет."""
    try:
        import psutil
    except ImportError:
        return 0.0, 0.0
    return float(psutil.cpu_percent(interval=None)), float(psutil.virtual_memory().percent)
