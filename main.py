"""Джарвис — десктопное приложение.

    python main.py                 запуск окна
    python main.py --devices       список аудиоустройств
    python main.py --selftest x.png  снимок интерфейса без микрофона
"""

from __future__ import annotations

import os

# OpenBLAS (внутри numpy) заранее резервирует буфер на каждое ядро процессора:
# на 16 потоках это было 500 МБ памяти, которые Юки никогда не использовала —
# тяжёлой матричной математики на процессоре у неё нет. Двух потоков хватает.
# Задать своё значение можно переменной окружения до запуска.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import argparse
from pathlib import Path

from core import config


def main() -> int:
    parser = argparse.ArgumentParser(description="Джарвис — локальный голосовой ассистент")
    parser.add_argument("--devices", action="store_true", help="показать аудиоустройства и выйти")
    parser.add_argument("--selftest", type=Path, default=None, help="сохранить снимок интерфейса и выйти")
    args = parser.parse_args()

    if args.devices:
        from core.audio import list_devices

        print(list_devices())
        return 0

    from desktop.app import run

    return run(config.load(), selftest=args.selftest)


if __name__ == "__main__":
    raise SystemExit(main())
