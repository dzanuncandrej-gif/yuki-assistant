"""Меню управления Юки: тёмный космический интерфейс поверх ассистента.

    settings.py      — чтение и запись разделов config.json
    controls.py      — элементы: переключатели, слайдеры, карточки, строки
    pages.py         — содержимое разделов меню
    control_menu.py  — само окно: боковая навигация, анимации, заголовок
"""

from __future__ import annotations

from .control_menu import ControlMenu
from .settings import SettingsStore

__all__ = ["ControlMenu", "SettingsStore"]
