"""Кладёт модель faster-whisper в models/whisper/<size>, чтобы рантайм не ходил в сеть.

Использование:
    python scripts/download_whisper.py            # размер берётся из config.json
    python scripts/download_whisper.py --size base
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_ROOT = ROOT / "models" / "whisper"
SIZES = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")

# turbo лежит в другом репозитории: это дистиллят large-v3, точный и быстрый
REPOS = {"large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo"}


def fix_socks_proxy() -> None:
    """httpx не умеет socks4/5 из системных настроек — подставляем локальный HTTP-прокси, если он есть."""
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return
    system = urllib.request.getproxies()
    if not any(str(url).startswith("socks") for url in system.values()):
        return
    for port in (10809, 10808, 8080):
        with socket.socket() as probe:
            probe.settimeout(0.4)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{port}"
                print(f"  используется HTTP-прокси 127.0.0.1:{port}")
                return
    print("  внимание: в системе включён SOCKS-прокси, HTTP-прокси не найден — загрузка может не пройти")


def configured_size() -> str:
    config_path = ROOT / "config.json"
    if not config_path.exists():
        return "small"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return str(data.get("stt", {}).get("model_size", "small"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка модели faster-whisper")
    parser.add_argument("--size", default=None, choices=SIZES)
    args = parser.parse_args()

    size = args.size or configured_size()
    target = TARGET_ROOT / size
    if (target / "model.bin").exists():
        print(f"Модель уже на месте: {target}")
        return 0

    fix_socks_proxy()
    from huggingface_hub import snapshot_download

    repo = REPOS.get(size, f"Systran/faster-whisper-{size}")
    print(f"Качаю {repo} → {target}")
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo,
        local_dir=str(target),
        allow_patterns=["*.bin", "*.json", "*.txt"],
    )
    print("Готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
