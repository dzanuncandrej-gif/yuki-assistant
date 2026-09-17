"""Зрение: снимок экрана или картинка описываются локальной vision-моделью Ollama.

Если такой модели нет, ассистент честно говорит об этом и отдаёт список окон,
а не выдумывает содержимое экрана.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import requests

VISION_HINTS = ("llava", "vision", "-vl", "vl-", "vl:", "moondream", "bakllava", "minicpm-v", "gemma3")

# чем меньше модель, тем быстрее она подгружается рядом с основной моделью агента
PREFERRED = ("qwen2.5vl", "qwen2-vl", "minicpm-v", "moondream", "llava")

# llava слушается английских инструкций заметно лучше, чем русских
DEFAULT_PROMPT = "Describe what is shown here in one or two short sentences. Be concrete."

TRANSLATE_PROMPT = "Переведи на русский язык кратко, одним-двумя предложениями, без пояснений:"

# Сколько модель зрения держится в памяти видеокарты после разбора кадра.
#
# Держать её там полчаса нельзя. Модель зрения и языковая модель вместе не влезают
# в восемь гигабайт, поэтому каждая вытесняет другую: после разбора экрана ответ
# голосом ждал перезагрузки языковой модели, а следующий кадр — перезагрузки
# зрения. Именно так разговор в видеорежиме доходил до полутора минут на реплику.
# Короткая жизнь означает: посмотрели — освободили память разговору.
LIVE_KEEP_ALIVE = "90s"


class VisionError(RuntimeError):
    """Нет модели зрения или она не ответила."""


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # Ollama локальна, системный прокси только мешает
    return session


def available_model(url: str) -> str | None:
    """Установленная модель зрения. Из нескольких выбираем самую лёгкую по списку PREFERRED."""
    try:
        response = _session().get(f"{url}/api/tags", timeout=3)
        response.raise_for_status()
        models = [str(item.get("name", "")) for item in response.json().get("models", ())]
    except (requests.RequestException, ValueError):
        return None

    candidates = [name for name in models if any(hint in name.lower() for hint in VISION_HINTS)]
    if not candidates:
        return None
    for family in PREFERRED:
        for name in candidates:
            if family in name.lower():
                return name
    return candidates[0]


def grab_screen() -> bytes:
    """Снимок экрана в PNG прямо в память — на диск ничего не пишем."""
    try:
        import pyautogui
    except ImportError as err:
        raise VisionError("нет модуля pyautogui") from err

    shot = pyautogui.screenshot()
    shot.thumbnail((768, 768))  # меньше картинка — заметно быстрее ответ модели
    buffer = io.BytesIO()
    shot.convert("RGB").save(buffer, format="JPEG", quality=82)
    return buffer.getvalue()


def _is_latin(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if "a" <= ch.lower() <= "z")
    return latin / len(letters) > 0.6


def to_russian(text: str, url: str, timeout_s: float = 60.0) -> str:
    """Модели зрения плохо говорят по-русски — перевод делает основная чат-модель."""
    if not _is_latin(text):
        return text
    try:
        tags = _session().get(f"{url}/api/tags", timeout=3).json().get("models", ())
        chat = next(
            (str(item["name"]) for item in tags
             if not any(hint in str(item["name"]).lower() for hint in VISION_HINTS)),
            None,
        )
        if chat is None:
            return text
        response = _session().post(
            f"{url}/api/chat",
            json={
                "model": chat,
                "stream": False,
                "keep_alive": "30m",
                "messages": [{"role": "user", "content": f"{TRANSLATE_PROMPT}\n\n{text}"}],
                "options": {"temperature": 0.1, "num_predict": 160},
            },
            timeout=timeout_s,
        )
        response.raise_for_status()
        translated = str(response.json().get("message", {}).get("content", "")).strip()
        return translated or text
    except (requests.RequestException, ValueError, KeyError):
        return text


def describe(
    image: bytes,
    url: str,
    model: str,
    prompt: str = DEFAULT_PROMPT,
    timeout_s: float = 120.0,
    num_predict: int = 160,
    keep_alive: str = LIVE_KEEP_ALIVE,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(image).decode("ascii")],
        "stream": False,
        # вне звонка модель зрения живёт недолго: она делит видеопамять с моделью агента
        "keep_alive": keep_alive,
        "options": {"temperature": 0.2, "num_predict": int(num_predict)},
    }
    try:
        response = _session().post(f"{url}/api/generate", json=payload, timeout=timeout_s)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as err:
        raise VisionError("модель зрения не ответила") from err
    text = str(data.get("response", "")).strip()
    if not text:
        raise VisionError("модель зрения вернула пустой ответ")
    return text


# эти модели уверенно отвечают по-русски — им не нужен перевод после описания
RU_CAPABLE = ("qwen2.5vl", "qwen2-vl", "minicpm-v", "gemma3")


def _prompt_for(model: str, question: str) -> str:
    """Русский вопрос понимают не все модели зрения — для остальных остаётся английский."""
    if any(family in model.lower() for family in RU_CAPABLE):
        base = question.strip() or "Что показано на экране?"
        return f"{base} Ответь кратко по-русски, одним-двумя предложениями."
    if question.strip() and question.strip() != DEFAULT_PROMPT:
        return f"{DEFAULT_PROMPT} Focus on: {question.strip()}"
    return DEFAULT_PROMPT


def _need_model(url: str) -> str:
    model = available_model(url)
    if model is None:
        raise VisionError("модель зрения не установлена. Выполни в консоли: ollama pull qwen2.5vl:3b")
    return model


def look_at_screen(url: str, prompt: str = DEFAULT_PROMPT) -> str:
    model = _need_model(url)
    return to_russian(describe(grab_screen(), url, model, _prompt_for(model, prompt)), url)


def look_at_file(path: Path, url: str, prompt: str = DEFAULT_PROMPT) -> str:
    if not path.exists():
        raise VisionError(f"файла нет: {path}")
    model = _need_model(url)
    return to_russian(describe(path.read_bytes(), url, model, _prompt_for(model, prompt)), url)
