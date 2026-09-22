"""Глобальная горячая клавиша: показать или скрыть окно, даже когда фокус в другой программе."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class GlobalHotkey(QObject):
    """Обёртка над pynput. Если библиотеки нет — молча работает вхолостую."""

    triggered = Signal()

    def __init__(self, combo: str = "<ctrl>+<alt>+j", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._combo = combo
        self._listener = None

    @property
    def combo_label(self) -> str:
        return self._combo.replace("<", "").replace(">", "").replace("+", "+").upper()

    def start(self) -> bool:
        try:
            from pynput import keyboard
        except ImportError:
            return False
        try:
            self._listener = keyboard.GlobalHotKeys({self._combo: self.triggered.emit})
            self._listener.daemon = True
            self._listener.start()
        except Exception:
            self._listener = None
            return False
        return True

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
