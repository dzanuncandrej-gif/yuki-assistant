"""Инструменты ввода и зрения: клавиатура, мышь, скриншоты, разбор изображения моделью."""

from __future__ import annotations

import time

from .. import automation, vision
from .. import windows as win
from .registry import param_int, param_str, tool

_KEY_ALIASES = {
    "энтер": "enter", "ввод": "enter", "эскейп": "esc", "escape": "esc", "таб": "tab",
    "пробел": "space", "контрол": "ctrl", "контрл": "ctrl", "control": "ctrl",
    "шифт": "shift", "альт": "alt", "винда": "win", "windows": "win", "делит": "delete",
    "бэкспейс": "backspace", "вверх": "up", "вниз": "down", "влево": "left", "вправо": "right",
}

_settings = {"ollama_url": "http://127.0.0.1:11434"}


def configure(ollama_url: str) -> None:
    _settings["ollama_url"] = ollama_url


@tool(
    "type_text",
    "Печатает текст в активное окно (кириллица идёт через буфер обмена). "
    "Перед этим убедись, что нужное окно в фокусе.",
    {
        "text": param_str("Что напечатать"),
        "press_enter": param_str("yes — нажать Enter после текста", enum=["yes", "no"]),
    },
    ["text"],
)
def _type_text(text: str, press_enter: str = "no") -> str:
    automation.type_text(text)
    target = win.active_window()
    if press_enter.strip().lower() in ("yes", "true", "да", "1"):
        time.sleep(0.15)
        automation.press_key("enter")
        return f"текст напечатан и отправлен в окно «{target.title if target else '—'}»"
    return f"текст напечатан в окне «{target.title if target else '—'}»"


@tool(
    "press_keys",
    "Нажимает сочетание клавиш: ctrl+c, alt+tab, win+d, enter, f5.",
    {
        "keys": param_str("Клавиши через + , например ctrl+shift+esc"),
        "times": param_int("Сколько раз повторить, по умолчанию 1"),
    },
    ["keys"],
)
def _press_keys(keys: str, times: int = 1) -> str:
    parts = [_KEY_ALIASES.get(part.strip().lower(), part.strip().lower()) for part in keys.replace(" ", "+").split("+")]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError("не понял, какие клавиши нажимать")
    for _ in range(max(1, min(20, times))):
        automation.press_hotkey(parts)
        time.sleep(0.05)
    return f"нажато {'+'.join(parts)}"


@tool(
    "mouse_click",
    "Клик мышью. Без координат кликает там, где сейчас курсор. "
    "Координаты бери из скриншота, предварительно посмотрев на экран.",
    {
        "x": param_int("Координата X в пикселях"),
        "y": param_int("Координата Y в пикселях"),
        "button": param_str("left, right или middle", enum=["left", "right", "middle"]),
        "clicks": param_int("Число кликов: 1 или 2"),
    },
)
def _mouse_click(x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> str:
    position = automation.mouse_click(x, y, button=button, clicks=clicks)
    return f"клик {button} в точке {position[0]},{position[1]}"


@tool(
    "mouse_move",
    "Перемещает курсор в точку экрана.",
    {"x": param_int("Координата X"), "y": param_int("Координата Y")},
    ["x", "y"],
)
def _mouse_move(x: int, y: int) -> str:
    position = automation.mouse_move(x, y)
    return f"курсор в точке {position[0]},{position[1]}"


@tool(
    "scroll",
    "Прокручивает содержимое под курсором. Отрицательное значение — вниз.",
    {"amount": param_int("Величина прокрутки, например -600")},
    ["amount"],
)
def _scroll(amount: int) -> str:
    return f"прокрутка {automation.scroll(amount)}"


@tool("screen_size", "Разрешение экрана в пикселях — нужно перед кликами по координатам.")
def _screen_size() -> str:
    width, height = automation.screen_size()
    return f"экран {width}x{height}"


@tool(
    "take_screenshot",
    "Делает снимок экрана и сохраняет его в Изображения/Юки.",
)
def _screenshot() -> str:
    path = automation.screenshot()
    return f"снимок сохранён: {path}"


@tool(
    "look_at_screen",
    "Разглядывает экран моделью зрения: картинки, игры, графики, оформление — всё, "
    "чего нет в тексте окна. Медленно и занимает видеопамять, поэтому сначала "
    "попробуй read_screen и read_window_text: они мгновенные и точные. Координат "
    "не даёт — нажимать по её описанию нельзя.",
    {"question": param_str("Что именно нужно разглядеть")},
)
def _look_at_screen(question: str = "") -> str:
    from .. import screen

    prompt = question.strip() or vision.DEFAULT_PROMPT
    # Через screen.look, а не напрямую: там снимается активное окно вместо всего
    # рабочего стола (мелкий текст читается вернее) и держится кэш по
    # неизменившемуся кадру — повторный тот же вопрос не будит модель заново.
    return screen.look(prompt, _settings["ollama_url"])


@tool(
    "look_at_image",
    "Описывает изображение из файла.",
    {"path": param_str("Путь к картинке"), "question": param_str("Что нужно узнать")},
    ["path"],
)
def _look_at_image(path: str, question: str = "") -> str:
    from .file_tools import resolve

    target = resolve(path, must_exist=True)
    return vision.look_at_file(target, _settings["ollama_url"], prompt=question.strip() or vision.DEFAULT_PROMPT)
