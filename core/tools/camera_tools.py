"""Инструменты камеры: кто перед экраном, запомнить лицо, посмотреть на человека."""

from __future__ import annotations

from .. import vision as vision_model
from .registry import param_str, tool

_runtime: dict[str, object] = {"camera": None, "ollama_url": "http://127.0.0.1:11434"}


def configure(camera: object, ollama_url: str) -> None:
    """Ассистент отдаёт сюда работающую камеру: инструменты сами её не открывают."""
    _runtime["camera"] = camera
    _runtime["ollama_url"] = ollama_url


def _camera():  # noqa: ANN202
    camera = _runtime["camera"]
    if camera is None or not getattr(camera, "running", False):
        raise RuntimeError("камера не включена — она работает в режиме видеосвязи")
    return camera


@tool("camera_look", "Смотрит в камеру и говорит, кто перед ней и один человек или несколько.")
def _camera_look() -> str:
    return _camera().describe()


@tool(
    "remember_face",
    "Запоминает лицо человека перед камерой под именем. После этого Юки узнаёт его.",
    {"name": param_str("Как зовут человека")},
    ["name"],
)
def _remember_face(name: str) -> str:
    return _camera().enroll(name)


@tool(
    "forget_face",
    "Убирает лицо из списка знакомых.",
    {"name": param_str("Имя, которое нужно забыть")},
    ["name"],
    confirm=True,
)
def _forget_face(name: str) -> str:
    return "забыл лицо" if _camera().forget_face(name) else "такого имени не знаю"


@tool(
    "camera_describe",
    "Разбирает кадр с камеры моделью зрения: как выглядит человек, что он держит, "
    "что происходит вокруг. Используй для вопросов про себя и комнату, а не про экран.",
    {"question": param_str("Что именно нужно рассмотреть")},
)
def _camera_describe(question: str = "") -> str:
    camera = _camera()
    url = str(_runtime["ollama_url"])
    model = vision_model.available_model(url)
    if model is None:
        raise RuntimeError("модель зрения не установлена")
    prompt = question.strip() or "Что видно на этом кадре с веб-камеры? Ответь одним-двумя предложениями."
    answer = vision_model.describe(
        camera.snapshot(), url, model, vision_model._prompt_for(model, prompt),  # noqa: SLF001
        timeout_s=45, num_predict=120, keep_alive=vision_model.LIVE_KEEP_ALIVE,
    )
    return vision_model.to_russian(answer, url)
