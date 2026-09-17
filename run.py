"""Точка входа: python run.py [--devices] [--no-browser] [--port 8765]."""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from core import config
from core.server import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Джарвис — локальный голосовой ассистент")
    parser.add_argument("--devices", action="store_true", help="показать аудиоустройства и выйти")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    if args.devices:
        from core.audio import list_devices

        print(list_devices())
        return 0

    cfg = config.load()
    host = args.host or cfg["server"]["host"]
    port = args.port or int(cfg["server"]["port"])
    url = f"http://{host}:{port}/"

    if cfg["server"]["open_browser"] and not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print(f"\n  Джарвис → {url}\n  Ctrl+C для выхода\n")
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
