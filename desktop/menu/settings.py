"""Хранилище настроек меню: живая копия конфигурации плюс запись в config.json.

Меню не трогает файл напрямую. Оно меняет значение в хранилище, хранилище
сообщает об изменении подписчикам (панель, ассистент) и откладывает запись на
диск — чтобы движение слайдера не превращалось в сотню сохранений.
"""

from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtCore import QObject, QTimer, Signal

from core import config

SAVE_DELAY_MS = 700


class SettingsStore(QObject):
    """Раздел → ключ → значение. Изменения приходят сигналом changed."""

    changed = Signal(str, str, object)   # section, key, value
    section_changed = Signal(str, dict)  # section, весь раздел целиком

    def __init__(self, cfg: Mapping[str, Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._data: dict[str, dict[str, Any]] = {
            key: dict(value) for key, value in cfg.items() if isinstance(value, Mapping)
        }
        self._dirty: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush)

    # ---------------------------------------------------------------- чтение

    def section(self, name: str) -> dict[str, Any]:
        return dict(self._data.get(name, {}))

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        return self._data.get(section, {}).get(key, fallback)

    # ---------------------------------------------------------------- запись

    def set(self, section: str, key: str, value: Any) -> None:
        block = self._data.setdefault(section, {})
        if block.get(key) == value:
            return
        block[key] = value
        self._dirty.add(section)
        self.changed.emit(section, key, value)
        self.section_changed.emit(section, dict(block))
        self._timer.start(SAVE_DELAY_MS)

    def flush(self) -> None:
        """Сброс на диск. Пишем только изменённые разделы — остальной конфиг не трогаем."""
        for name in tuple(self._dirty):
            try:
                config.save_section(name, self._data.get(name, {}))
            except OSError:
                continue
            self._dirty.discard(name)
