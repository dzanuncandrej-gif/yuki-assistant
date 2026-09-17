"""Инструменты сети: поиск, чтение страниц, новости, погода, музыка, работа с браузером."""

from __future__ import annotations

from .. import browser, media, web
from .registry import param_int, param_str, tool


@tool(
    "web_search",
    "Ищет в интернете и возвращает заголовки, описания и ссылки. Используй для любых "
    "вопросов о текущих событиях, ценах, фактах, которых нет в памяти.",
    {
        "query": param_str("Поисковый запрос"),
        "count": param_int("Сколько результатов вернуть, 1..8"),
    },
    ["query"],
)
def _web_search(query: str, count: int = 5) -> str:
    results = web.search_web(query, count=max(1, min(8, count)))
    return web.summarize_results(results, limit=count)


@tool(
    "read_webpage",
    "Скачивает страницу по ссылке и возвращает её текст. Нужен, чтобы прочитать статью целиком.",
    {
        "url": param_str("Адрес страницы"),
        "limit": param_int("Сколько символов вернуть, по умолчанию 3000"),
    },
    ["url"],
)
def _read_webpage(url: str, limit: int = 3000) -> str:
    return web.read_page(url, limit=max(500, min(8000, limit)))


@tool(
    "get_news",
    "Свежие новости из лент. Тема: главное, технологии, спорт, бизнес, наука, мир — "
    "или любые ключевые слова.",
    {
        "topic": param_str("Тема новостей, по умолчанию «главное»"),
        "count": param_int("Сколько новостей, 3..10"),
    },
)
def _get_news(topic: str = "главное", count: int = 6) -> str:
    stories = web.news(topic, count=max(3, min(10, count)))
    return web.summarize_results(stories, limit=count)


@tool(
    "get_weather",
    "Текущая погода. Город можно не указывать — возьмётся по умолчанию из настроек.",
    {"city": param_str("Город, необязательно")},
)
def _weather(city: str = "") -> str:
    return web.weather(city or None)


@tool(
    "get_forecast",
    "Прогноз погоды на ближайшие дни.",
    {"city": param_str("Город, необязательно"), "days": param_int("Сколько дней, 1..3")},
)
def _forecast(city: str = "", days: int = 2) -> str:
    return web.forecast(city or None, days=days)


@tool(
    "play_music",
    "Включает музыку: трек, исполнителя, альбом или жанр — через YouTube. Прошлый трек, "
    "включённый Юки, закрывается сам. «Другую песню» так не включают — это media_control next.",
    {"query": param_str("Что включить по-русски или как пишется название: «Кино Группа крови», "
                        "«спокойная музыка». Пусто — просто музыка")},
)
def _play_music(query: str = "") -> str:
    return f"включено: {media.play_music(query or None)}"


@tool(
    "play_video",
    "Включает видео на YouTube: ролик, фильм, клип, обзор, мультик, рецепт — сразу первый "
    "подходящий ролик.",
    {"query": param_str("Что за видео, по-русски: «как приготовить борщ», «обзор айфона 17»")},
    ["query"],
)
def _play_video(query: str) -> str:
    return f"включено видео: {media.play_video(query)}"


@tool(
    "open_website",
    "Открывает сайт в браузере и убеждается, что окно браузера появилось.",
    {"url": param_str("Адрес сайта или его название, например youtube.com")},
    ["url"],
)
def _open_website(url: str) -> str:
    return f"открыт браузер: «{browser.open_url(url)}»"


@tool(
    "browser_search",
    "Открывает поисковую выдачу в браузере (google, yandex, youtube, duckduckgo).",
    {
        "query": param_str("Что искать"),
        "engine": param_str("Поисковик", enum=["google", "yandex", "duckduckgo", "youtube"]),
    },
    ["query"],
)
def _browser_search(query: str, engine: str = "google") -> str:
    return f"открыта выдача: «{browser.search(query, engine)}»"


@tool(
    "browser_goto",
    "Переходит по адресу в уже открытом браузере через адресную строку.",
    {"url": param_str("Адрес страницы")},
    ["url"],
)
def _browser_goto(url: str) -> str:
    return f"страница: «{browser.go_to(url)}»"


@tool(
    "browser_page_text",
    "Читает текст открытой в браузере вкладки (выделение и копирование). "
    "Нужен, когда страница за авторизацией и по ссылке её не скачать.",
    {"limit": param_int("Сколько символов вернуть")},
)
def _browser_page_text(limit: int = 3000) -> str:
    return browser.page_text(limit=max(500, min(8000, limit)))


@tool(
    "browser_control",
    "Действия во вкладках браузера: новая вкладка, закрыть вкладку, назад, прокрутка, поиск на странице.",
    {
        "action": param_str(
            "Одно из: new_tab, close_tab, back, scroll_down, scroll_up, find",
            enum=["new_tab", "close_tab", "back", "scroll_down", "scroll_up", "find"],
        ),
        "value": param_str("Для new_tab — адрес, для find — искомый текст"),
    },
    ["action"],
)
def _browser_control(action: str, value: str = "") -> str:
    key = action.strip().lower()
    if key == "new_tab":
        return f"вкладка: «{browser.new_tab(value or None)}»"
    if key == "close_tab":
        return browser.close_tab()
    if key == "back":
        return f"назад: «{browser.back()}»"
    if key == "scroll_down":
        return browser.scroll(-700)
    if key == "scroll_up":
        return browser.scroll(700)
    if key == "find":
        if not value.strip():
            raise ValueError("нечего искать на странице")
        return f"найдено на странице: {browser.find_on_page(value)}"
    raise ValueError("допустимо: new_tab, close_tab, back, scroll_down, scroll_up, find")
