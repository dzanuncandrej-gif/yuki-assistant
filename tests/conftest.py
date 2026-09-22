"""Общая настройка тестов: корень проекта в путях импорта.

Тесты намеренно не трогают ни микрофон, ни окна, ни сеть. Всё, что здесь
проверяется, — чистая логика: разбор речи, сопоставление имён, шаблоны команд,
переводы интерфейса и флаги безопасности инструментов.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
