"""Сторож Ollama: модель должна работать на видеокарте, а не на процессоре.

1 октября 2026 Ollama обновился сам и стартовал, пока установщик ещё копировал
файлы: не нашёл `llama-server.exe`, решил, что видеокарты нет, и считал всё на
процессоре. Ответы шли больше минуты, и выглядело это как «Юки тупит».

Проверка простая: `/api/ps` показывает, сколько модели лежит в видеопамяти.
Если почти ничего — перезапускаем Ollama, она заново находит видеокарту.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import requests

# доля модели в видеопамяти, ниже которой считаем, что Ollama на процессоре
_GPU_SHARE = 0.5


def check(url: str) -> str:
    """'gpu', 'cpu' или 'unknown' — где сейчас загружены модели."""
    try:
        models = requests.get(f"{url}/api/ps", timeout=3).json().get("models") or []
    except (requests.RequestException, ValueError):
        return "unknown"
    if not models:
        return "unknown"
    total = sum(int(item.get("size") or 0) for item in models)
    vram = sum(int(item.get("size_vram") or 0) for item in models)
    if total <= 0:
        return "unknown"
    return "gpu" if vram / total >= _GPU_SHARE else "cpu"


def _app_path() -> Path | None:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
    for name in ("ollama app.exe", "ollama.exe"):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def restart(url: str, timeout_s: float = 30.0) -> bool:
    """Перезапускает Ollama и ждёт, пока сервер снова ответит."""
    app = _app_path()
    if app is None:
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for name in ("ollama app.exe", "ollama.exe", "llama-server.exe"):
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True, creationflags=flags)
    time.sleep(1.5)
    if app.name == "ollama.exe":
        subprocess.Popen([str(app), "serve"], creationflags=flags | getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        os.startfile(str(app))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{url}/api/version", timeout=2).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False
