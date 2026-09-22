"""Живые данные из сети: поиск, чтение страниц, новости, погода, музыка.

Все источники работают без ключей: DuckDuckGo, RSS Google News, wttr.in, поиск YouTube.
Ключи (если появятся в .env) используются только как ускорители, не как обязательное условие.
"""

from __future__ import annotations

import re
import threading
import webbrowser
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests

TIMEOUT_S = 10.0
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

_WIND_DIRS = {
    "N": "северный", "NNE": "северо-северо-восточный", "NE": "северо-восточный",
    "ENE": "восточно-северо-восточный", "E": "восточный", "ESE": "восточно-юго-восточный",
    "SE": "юго-восточный", "SSE": "юго-юго-восточный", "S": "южный",
    "SSW": "юго-юго-западный", "SW": "юго-западный", "WSW": "западно-юго-западный",
    "W": "западный", "WNW": "западно-северо-западный", "NW": "северо-западный",
    "NNW": "северо-северо-западный",
}

# ленты новостей: без ключей, отдают свежие заголовки за минуты
NEWS_FEEDS: dict[str, tuple[str, ...]] = {
    "главное": (
        "https://news.google.com/rss?hl=ru&gl=RU&ceid=RU:ru",
        "https://lenta.ru/rss/news",
        "https://tass.ru/rss/v2.xml",
    ),
    "технологии": (
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ru&gl=RU&ceid=RU:ru",
        "https://habr.com/ru/rss/news/",
    ),
    "спорт": ("https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ru&gl=RU&ceid=RU:ru",),
    "бизнес": ("https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ru&gl=RU&ceid=RU:ru",),
    "наука": ("https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=ru&gl=RU&ceid=RU:ru",),
    "мир": ("https://news.google.com/rss/headlines/section/topic/WORLD?hl=ru&gl=RU&ceid=RU:ru",),
}


class WebError(RuntimeError):
    """Сеть недоступна или сервис не ответил."""


_defaults: dict[str, str] = {"default_city": ""}
_session_lock = threading.Lock()
_shared: requests.Session | None = None


def configure(settings: dict[str, str] | None) -> None:
    """Значения из config.json. Город нужен, когда VPN выдаёт чужую геолокацию."""
    if settings:
        _defaults.update({key: str(value) for key, value in settings.items()})


def _session() -> requests.Session:
    """Одна сессия на процесс: keep-alive экономит рукопожатие TLS на каждом запросе."""
    global _shared
    with _session_lock:
        if _shared is None:
            session = requests.Session()
            session.headers.update(_HEADERS)
            adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _shared = session
        return _shared


def open_url(url: str) -> str:
    webbrowser.open(url)
    return url


# ---------------------------------------------------------------- поиск


@dataclass(frozen=True)
class Result:
    title: str
    url: str
    snippet: str

    def as_text(self) -> str:
        host = urlparse(self.url).netloc
        return f"{self.title} ({host}): {self.snippet}".strip()


def _ddgs_search(query: str, count: int) -> tuple[Result, ...]:
    """Основной путь: библиотека ddgs обходит защиту DuckDuckGo и отдаёт разметку."""
    try:
        from ddgs import DDGS
    except ImportError:
        return ()
    try:
        with DDGS(timeout=int(TIMEOUT_S)) as engine:
            rows = engine.text(query, region="ru-ru", safesearch="off", max_results=count)
        return tuple(
            Result(str(row.get("title", "")), str(row.get("href", "")), str(row.get("body", "")))
            for row in rows
            if row.get("title")
        )
    except Exception:
        return ()


def _html_search(query: str, count: int) -> tuple[Result, ...]:
    """Запасной путь: HTML-версия DuckDuckGo, разбор через BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ()
    try:
        response = _session().post(
            "https://html.duckduckgo.com/html/", data={"q": query, "kl": "ru-ru"}, timeout=TIMEOUT_S
        )
        response.raise_for_status()
    except requests.RequestException:
        return ()

    soup = BeautifulSoup(response.text, "lxml")
    results: list[Result] = []
    for block in soup.select("div.result")[: count * 2]:
        link = block.select_one("a.result__a")
        if link is None:
            continue
        snippet = block.select_one(".result__snippet")
        href = str(link.get("href", ""))
        results.append(
            Result(link.get_text(" ", strip=True), href, snippet.get_text(" ", strip=True) if snippet else "")
        )
        if len(results) >= count:
            break
    return tuple(results)


def search_web(query: str, count: int = 5) -> tuple[Result, ...]:
    """Результаты поиска — сначала через ddgs, при неудаче через HTML-выдачу."""
    clean = query.strip()
    if not clean:
        raise WebError("пустой поисковый запрос")
    results = _ddgs_search(clean, count) or _html_search(clean, count)
    if not results:
        raise WebError("поисковик не ответил")
    return results


def search(query: str) -> str:
    """Совместимость со старым API: открывает выдачу и отдаёт краткую справку."""
    open_url(f"https://www.google.com/search?q={quote_plus(query)}")
    try:
        results = search_web(query, count=3)
    except WebError:
        return instant_answer(query) or ""
    return " | ".join(item.as_text() for item in results)


def instant_answer(query: str) -> str | None:
    """Короткий факт из DuckDuckGo Instant Answer, если он есть."""
    try:
        response = _session().get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    for key in ("AbstractText", "Answer", "Definition"):
        value = str(data.get(key) or "").strip()
        if value:
            return value[:400]
    for topic in data.get("RelatedTopics") or []:
        value = str(topic.get("Text") or "").strip()
        if value:
            return value[:400]
    return None


# ---------------------------------------------------------------- чтение страниц

_SCRIPTS = ("script", "style", "noscript", "svg", "form", "nav", "footer", "header", "aside")


def read_page(url: str, limit: int = 4000) -> str:
    """Читаемый текст страницы: снимает разметку и служебные блоки."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        response = _session().get(url, timeout=TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as err:
        raise WebError(f"страница не открылась: {err.__class__.__name__}") from err

    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type and "xml" not in content_type:
        return response.text[:limit]

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return re.sub(r"<[^>]+>", " ", response.text)[:limit]

    soup = BeautifulSoup(response.text, "lxml")
    for tag in soup(list(_SCRIPTS)):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
    if not text.strip():
        raise WebError("на странице нет текста")
    return text[:limit]


# ---------------------------------------------------------------- новости


@dataclass(frozen=True)
class Story:
    title: str
    source: str
    summary: str
    url: str


_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    import html

    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", text or ""))).strip()


def news(topic: str | None = None, count: int = 6) -> tuple[Story, ...]:
    """Свежие новости из RSS. topic — «главное», «технологии», «спорт» или свободный запрос."""
    import feedparser

    key = (topic or "главное").strip().lower()
    feeds = NEWS_FEEDS.get(key)
    if feeds is None:
        # произвольная тема — новостной поиск Google по ключевым словам
        feeds = (f"https://news.google.com/rss/search?q={quote_plus(key)}&hl=ru&gl=RU&ceid=RU:ru",)

    stories: list[Story] = []
    seen: set[str] = set()
    for feed_url in feeds:
        try:
            raw = _session().get(feed_url, timeout=TIMEOUT_S)
            raw.raise_for_status()
            parsed = feedparser.parse(raw.content)
        except (requests.RequestException, ValueError):
            continue
        for entry in parsed.entries[: count * 2]:
            title = _clean(getattr(entry, "title", ""))
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            source = ""
            if getattr(entry, "source", None) is not None:
                source = _clean(getattr(entry.source, "title", ""))
            if not source:
                source = urlparse(feed_url).netloc
            stories.append(
                Story(title, source, _clean(getattr(entry, "summary", ""))[:400], getattr(entry, "link", ""))
            )
            if len(stories) >= count:
                break
        if len(stories) >= count:
            break

    if not stories:
        raise WebError("новостные ленты не ответили")
    return tuple(stories)


# ---------------------------------------------------------------- погода


def _degrees(value: str) -> str:
    number = int(value)
    tail = abs(number) % 10
    teen = 10 <= abs(number) % 100 <= 20
    word = "градус" if tail == 1 and not teen else "градуса" if 2 <= tail <= 4 and not teen else "градусов"
    return f"{number:+d} {word}".replace("+", "плюс ").replace("-", "минус ")


def weather(city: str | None = None, open_browser: bool = False) -> str:
    """Текущая погода одной фразой."""
    location = (city or _defaults.get("default_city") or "").strip()
    url = f"https://wttr.in/{quote_plus(location)}?format=j1&lang=ru"
    try:
        response = _session().get(url, timeout=TIMEOUT_S)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as err:
        raise WebError("сервис погоды не ответил") from err

    try:
        current = data["current_condition"][0]
        area = data["nearest_area"][0]
        place = area.get("areaName", [{}])[0].get("value") or location or "вашем городе"
        description = (current.get("lang_ru") or current.get("weatherDesc") or [{}])[0].get("value", "")
        temp = _degrees(current["temp_C"])
        feels = _degrees(current["FeelsLikeC"])
        wind = current.get("windspeedKmph", "0")
        direction = _WIND_DIRS.get(current.get("winddir16Point", ""), "")
    except (KeyError, IndexError) as err:
        raise WebError("не разобрал ответ сервиса погоды") from err

    if open_browser:
        open_url(f"https://yandex.ru/pogoda/search?request={quote_plus('погода ' + place)}")

    parts = [f"В городе {place}: {description.lower()}" if description else f"В городе {place}"]
    parts.append(f"{temp}, ощущается как {feels}")
    if wind and wind != "0":
        parts.append(f"ветер {direction} {wind} километров в час" if direction else f"ветер {wind} километров в час")
    return ", ".join(parts) + "."


def forecast(city: str | None = None, days: int = 2) -> str:
    """Прогноз на ближайшие дни — минимум, максимум и описание."""
    location = (city or _defaults.get("default_city") or "").strip()
    try:
        response = _session().get(
            f"https://wttr.in/{quote_plus(location)}?format=j1&lang=ru", timeout=TIMEOUT_S
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as err:
        raise WebError("сервис погоды не ответил") from err

    parts: list[str] = []
    for day in data.get("weather", ())[: max(1, min(3, days))]:
        hourly = day.get("hourly", ())
        noon = hourly[len(hourly) // 2] if hourly else {}
        description = (noon.get("lang_ru") or noon.get("weatherDesc") or [{}])[0].get("value", "")
        parts.append(
            f"{day.get('date', '')}: от {day.get('mintempC')} до {day.get('maxtempC')} градусов"
            + (f", {description.lower()}" if description else "")
        )
    if not parts:
        raise WebError("прогноз не разобран")
    return "; ".join(parts)


# ---------------------------------------------------------------- музыка


def youtube_video_id(query: str) -> str | None:
    """Первый ролик из выдачи YouTube — без ключей, разбором страницы результатов."""
    try:
        response = _session().get(
            "https://www.youtube.com/results", params={"search_query": query}, timeout=TIMEOUT_S
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    match = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', response.text)
    return match.group(1) if match else None


def play_music(query: str | None = None) -> str:
    """Открывает YouTube и запускает воспроизведение. Возвращает описание того, что включено."""
    request = (query or "музыка").strip()
    video = youtube_video_id(request)
    if video:
        open_url(f"https://www.youtube.com/watch?v={video}&autoplay=1")
        return request
    open_url(f"https://www.youtube.com/results?search_query={quote_plus(request)}")
    return f"{request} (открыл выдачу — выберите ролик)"


def summarize_results(results: Iterable[Any], limit: int = 5) -> str:
    """Компактный текст выдачи для передачи в модель."""
    lines = []
    for index, item in enumerate(list(results)[:limit], start=1):
        if isinstance(item, Result):
            lines.append(f"{index}. {item.title} — {item.snippet} [{item.url}]")
        elif isinstance(item, Story):
            lines.append(f"{index}. {item.title} ({item.source}) — {item.summary}")
    return "\n".join(lines)
