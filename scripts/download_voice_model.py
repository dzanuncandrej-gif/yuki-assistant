"""Скачивает основную модель синтеза речи Silero (все три голоса Джарвиса сразу).

    python scripts/download_voice_model.py

Модель ~38 МБ, работает офлайн на процессоре и синтезирует шесть секунд речи
примерно за пять сотых секунды.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import voices  # noqa: E402


def main() -> int:
    target = voices.SILERO_PATH
    if voices.silero_ready():
        print(f"Модель уже на месте: {target} ({target.stat().st_size / 1024 / 1024:.0f} МБ)")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"↓ {voices.SILERO_URL}")
    try:
        with urllib.request.urlopen(voices.SILERO_URL, timeout=120) as response, target.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done * 100 // total}%", end="", flush=True)
    except urllib.error.URLError as err:
        target.unlink(missing_ok=True)
        raise SystemExit(f"Не удалось скачать модель: {err}") from err

    print(f"\rГотово: {target} ({target.stat().st_size / 1024 / 1024:.0f} МБ)")
    print("Голоса: " + ", ".join(f"{p.title} ({p.silero_speaker})" for p in voices.catalog()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
