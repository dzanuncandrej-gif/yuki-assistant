"""Скачивает голоса Piper в models/piper/.

    python scripts/download_piper_voice.py                # все три голоса Джарвиса
    python scripts/download_piper_voice.py --profile atlas
    python scripts/download_piper_voice.py --voice ru_RU-denis-medium
    python scripts/download_piper_voice.py --list
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import voices  # noqa: E402 — путь к проекту добавляется выше

TARGET_DIR = ROOT / "models" / "piper"
BASE = voices.BASE_URL

# голоса вне профилей — на случай, если захочется собрать свой персонаж
EXTRA: dict[str, str] = {
    "ru_RU-denis-medium": "ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx",
    "en_US-ryan-high": "en/en_US/ryan/high/en_US-ryan-high.onnx",
    "en_GB-alan-medium": "en/en_GB/alan/medium/en_GB-alan-medium.onnx",
}


def _download(url: str, target: Path) -> None:
    print(f"  ↓ {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r    {done * 100 // total}%", end="", flush=True)
        print(f"\r    готово → {target.name}")
    except urllib.error.URLError as err:
        target.unlink(missing_ok=True)
        raise SystemExit(f"Не удалось скачать: {err}") from err


def _fetch(name: str, remote: str) -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    model = TARGET_DIR / f"{name}.onnx"
    settings = TARGET_DIR / f"{name}.onnx.json"
    if model.exists() and settings.exists():
        print(f"  · {name} уже на месте")
        return
    if not model.exists():
        _download(f"{BASE}/{remote}", model)
    if not settings.exists():
        _download(f"{BASE}/{remote}.json", settings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка голосов Piper")
    parser.add_argument("--profile", choices=[p.key for p in voices.catalog()], help="один голос Джарвиса")
    parser.add_argument("--voice", choices=sorted(EXTRA), help="произвольный голос Piper")
    parser.add_argument("--all", action="store_true", help="все голоса профилей (поведение по умолчанию)")
    parser.add_argument("--list", action="store_true", help="показать голоса и их состояние")
    args = parser.parse_args()

    if args.list:
        for profile in voices.catalog():
            state = "установлен" if profile.installed else "не скачан"
            print(f"{profile.key:8} {profile.title:9} {profile.character:32} {profile.model_name} — {state}")
        for name in sorted(EXTRA):
            print(f"{'—':8} {'':9} {'дополнительный':32} {name}")
        return 0

    if args.voice:
        _fetch(args.voice, EXTRA[args.voice])
        print(f"\nГолос скачан. Пропиши в config.json: \"piper_model\": \"models/piper/{args.voice}.onnx\"")
        return 0

    targets = voices.catalog()
    if args.profile:
        targets = tuple(p for p in targets if p.key == args.profile)

    for profile in targets:
        print(f"\n{profile.title} — {profile.character}")
        _fetch(profile.model_name, profile.remote)

    ready = [p.title for p in voices.catalog() if p.installed]
    print(f"\nГотово. Установлены голоса: {', '.join(ready) or 'нет'}")
    print("Переключение: скажи «переключись на атлас» или выбери голос в окне программы.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
