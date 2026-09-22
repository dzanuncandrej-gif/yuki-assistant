"""Инструменты учебного режима: решение задач текстом, с экрана, с камеры и с фото."""

from __future__ import annotations

from .. import education
from .. import vision as vision_model
from .registry import param_str, tool

_runtime: dict[str, object] = {"agent": None, "ollama_url": "http://127.0.0.1:11434", "camera": None}


def configure(agent: object, ollama_url: str) -> None:
    _runtime["agent"] = agent
    _runtime["ollama_url"] = ollama_url


def set_camera(camera: object) -> None:
    _runtime["camera"] = camera


def _agent():
    agent = _runtime["agent"]
    if agent is None or not getattr(agent, "available", lambda: False)():
        raise RuntimeError("языковая модель недоступна — запусти ollama serve")
    return agent


def solve(task: str, subject: str = "", grade: str = "") -> str:
    """Общий путь: собрать промпт, решить, пересчитать арифметику."""
    clean = str(task or "").strip()
    if len(clean) < 5:
        raise ValueError("не вижу условия задачи")

    raw = _agent().ask(education.build_prompt(clean, subject, grade), num_predict=900)
    if not raw:
        raise RuntimeError("модель не ответила")
    solution = education.clean_solution(raw)
    warning = education.verify_arithmetic(solution)
    return f"{solution}\n\n{warning}" if warning else solution


def read_image(image: bytes, hint: str = "") -> str:
    """Расшифровывает задание с картинки моделью зрения."""
    url = str(_runtime["ollama_url"])
    model = vision_model.available_model(url)
    if model is None:
        raise RuntimeError("модель зрения не установлена")
    prompt = education.VISION_PROMPT + (f" Подсказка: {hint}" if hint else "")
    text = vision_model.describe(
        image, url, model, prompt, timeout_s=90, num_predict=420,
        keep_alive=vision_model.LIVE_KEEP_ALIVE,
    )
    return text.strip()


@tool(
    "solve_task",
    "Решает школьное задание по любому предмету до 11 класса с подробным разбором: "
    "дано, решение по шагам, формулы, вычисления, проверка и ответ. "
    "Используй, когда просят решить задачу, пример, уравнение или объяснить тему.",
    {
        "task": param_str("Условие задания целиком"),
        "subject": param_str("Предмет, если известен: математика, физика, химия…"),
        "grade": param_str("Класс, если назван"),
    },
    ["task"],
)
def _solve_task(task: str, subject: str = "", grade: str = "") -> str:
    return solve(task, subject, grade)


@tool(
    "solve_from_screen",
    "Читает задание прямо с экрана (учебник, сайт, документ) и решает его с разбором.",
    {"hint": param_str("Что именно решать, если на экране несколько заданий")},
)
def _solve_from_screen(hint: str = "") -> str:
    from .. import live

    watcher = live.Watcher(str(_runtime["ollama_url"]))
    task = read_image(watcher.grab(side=900), hint)
    return f"Задание с экрана:\n{task}\n\n{solve(task)}"


@tool(
    "solve_from_camera",
    "Смотрит в камеру на тетрадь или учебник, распознаёт задание и решает его.",
    {"hint": param_str("Уточнение, если в кадре несколько заданий")},
)
def _solve_from_camera(hint: str = "") -> str:
    camera = _runtime["camera"]
    if camera is None or not getattr(camera, "running", False):
        raise RuntimeError("камера включается в режиме видеосвязи")
    task = read_image(camera.snapshot(side=900, quality=88), hint)
    return f"Задание с камеры:\n{task}\n\n{solve(task)}"


@tool(
    "explain_topic",
    "Объясняет школьную тему простым языком с примерами — когда просят «объясни», "
    "«как это работает», «расскажи про».",
    {"topic": param_str("Тема"), "grade": param_str("Класс, если назван")},
    ["topic"],
)
def _explain_topic(topic: str, grade: str = "") -> str:
    prompt = (
        "Объясни школьнику тему простым языком: суть, зачем нужно, формулы или правила, "
        "два примера с разбором и типичные ошибки. По-русски, без markdown.\n\n"
        f"Тема: {topic}." + (f" Класс: {grade}." if grade else "")
    )
    answer = _agent().ask(prompt, num_predict=700)
    if not answer:
        raise RuntimeError("модель не ответила")
    return education.clean_solution(answer)
