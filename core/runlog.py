"""Журнал data/yuki.log: что Юки делала, с отметками времени.

Пульт показывает то же самое, но после закрытия окна оно пропадает. По журналу
видно, где ушло время (задержки) и что сломалось, — и у себя, и у любого
пользователя, который пришлёт файл.
"""

from __future__ import annotations

import threading
import time

from . import bus, config

PATH = config.ROOT / "data" / "yuki.log"
_LIMIT = 1_000_000
_lock = threading.Lock()
_started = time.monotonic()


def _line(event: dict) -> str | None:
    kind = event.get("type")
    if kind == "message":
        return f"{event.get('kind', '?'):9} {str(event.get('text', ''))[:600]}"
    if kind == "state":
        return f"state     {event.get('state')}"
    if kind == "coder" and event.get("event") in ("step", "done", "check"):
        return f"coder     {event.get('event')}: {event.get('text', '')}"
    return None


def _write(event: dict) -> None:
    line = _line(event)
    if line is None:
        return
    stamp = time.strftime("%H:%M:%S") + f" +{time.monotonic() - _started:7.1f}s"
    with _lock:
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            if PATH.exists() and PATH.stat().st_size > _LIMIT:
                PATH.replace(PATH.with_suffix(".old.log"))
            with PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp}  {line}\n")
        except OSError:
            pass


def start() -> None:
    _write({"type": "message", "kind": "system", "text": "=== запуск Юки ==="})
    bus.bus.subscribe_callback(_write)
