"""Один размер контекста на все запросы к Ollama.

Ollama держит модель загруженной с конкретным `num_ctx`. Запрос с другим числом
(или вовсе без него — тогда берётся умолчание) заставляет её выгрузить и заново
загрузить веса: 3–5 секунд тишины. Раньше так случалось на первом вопросе после
прогрева, на каждом вопросе про экран и на каждом обращении к консультанту.
"""

from __future__ import annotations

_value: int | None = None


def num_ctx() -> int:
    global _value
    if _value is None:
        try:
            from . import config

            _value = int(config.load().get("brain", {}).get("num_ctx", 6144))
        except Exception:
            _value = 6144
    return _value
