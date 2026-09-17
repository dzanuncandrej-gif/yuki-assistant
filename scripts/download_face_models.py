"""Скачивает модели распознавания лиц (YuNet + SFace) в models/face/.

    python scripts/download_face_models.py

YuNet находит лицо (230 КБ), SFace превращает его в вектор для сравнения (37 МБ).
Обе работают на процессоре в реальном времени и не требуют интернета после установки.
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "models" / "face"
BASE = "https://github.com/opencv/opencv_zoo/raw/main/models"

HANDS = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/"
    "float16/1/hand_landmarker.task"
)

FILES = {
    "face_detection_yunet_2023mar.onnx": f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    # руки: жесты управляют музыкой и громкостью
    "hand_landmarker.task": HANDS,
}


def fix_socks_proxy() -> None:
    """Системный SOCKS-прокси ломает загрузку — подставляем локальный HTTP, если он есть."""
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return
    if not any(str(url).startswith("socks") for url in urllib.request.getproxies().values()):
        return
    for port in (10809, 10808, 8080):
        with socket.socket() as probe:
            probe.settimeout(0.4)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{port}"
                print(f"  через HTTP-прокси 127.0.0.1:{port}")
                return


def download(url: str, target: Path) -> None:
    print(f"  ↓ {target.name}")
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r    {done * 100 // total}%", end="", flush=True)
        print(f"\r    готово: {target.stat().st_size / 1024:.0f} КБ")
    except urllib.error.URLError as err:
        target.unlink(missing_ok=True)
        raise SystemExit(f"Не удалось скачать {target.name}: {err}") from err


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    fix_socks_proxy()
    for name, url in FILES.items():
        path = TARGET / name
        if path.exists() and path.stat().st_size > 10_000:
            print(f"  · {name} уже на месте")
            continue
        download(url, path)
    print("\nГотово. Джарвис теперь узнаёт лица.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
