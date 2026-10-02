"""Знакомство с Юки при первом запуске: проверка системы, голос, имя, обучение.

Страница — `ui3d/onboarding.html`; здесь окно, проверки и связь с ассистентом.
Проверки идут в фоне и приходят странице по одной, как только готовы: человек
видит, что именно проверяется и что делать, если что-то не так.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QPainterPath, QRegion
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core import bus, config, voices

from .bridge import Bridge
from .webpanel import build_view, event_json

WINDOW_SIZE = (1180, 760)


class OnboardingLink(QObject):
    event = Signal(str)
    checks = Signal(str)
    profile = Signal(str)

    page_ready = Signal()
    speak_requested = Signal(str)
    preview_requested = Signal(str)
    voice_chosen = Signal(str)
    name_given = Signal(str)
    checks_requested = Signal()
    finished = Signal()
    call_requested = Signal()

    @Slot()
    def ready(self) -> None:
        self.page_ready.emit()

    @Slot(str)
    def say(self, text: str) -> None:
        self.speak_requested.emit(text)

    @Slot(str)
    def preview(self, key: str) -> None:
        self.preview_requested.emit(key)

    @Slot(str)
    def setVoice(self, key: str) -> None:
        self.voice_chosen.emit(key)

    @Slot(str)
    def setName(self, name: str) -> None:
        self.name_given.emit(name)

    @Slot()
    def runChecks(self) -> None:
        self.checks_requested.emit()

    @Slot()
    def finish(self) -> None:
        self.finished.emit()

    @Slot()
    def startCall(self) -> None:
        self.call_requested.emit()


class OnboardingWindow(QWidget):
    """Окно знакомства. Закрывается кнопкой «Начать», «Пропустить» или Esc."""

    closed = Signal()
    call_requested = Signal()
    _check_ready = Signal(str)  # результат проверки из фонового потока

    def __init__(self, assistant: Any, bridge: Bridge, store: Any = None) -> None:
        super().__init__(None)
        self._assistant = assistant
        self._bridge = bridge
        self._store = store
        self._live = False

        self.setWindowTitle("Юки — знакомство")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setStyleSheet("background: #03050b;")
        self.resize(*WINDOW_SIZE)

        self.link = OnboardingLink(self)
        self.link.page_ready.connect(self._on_ready)
        self.link.speak_requested.connect(self._say)
        self.link.preview_requested.connect(self._preview)
        self.link.voice_chosen.connect(self._choose_voice)
        self.link.name_given.connect(self._set_name)
        self.link.checks_requested.connect(self._run_checks)
        self.link.finished.connect(self.finish)
        self.link.call_requested.connect(self.call_requested.emit)
        self._check_ready.connect(self.link.checks.emit)

        self.view = build_view("onboarding.html", self.link, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        bridge.event.connect(self._forward)

    # ---------------------------------------------------------------- окно

    def open(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 22, 22)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def mousePressEvent(self, event) -> None:
        handle = self.windowHandle()
        if handle is not None and event.button() == Qt.MouseButton.LeftButton:
            handle.startSystemMove()
        super().mousePressEvent(event)

    def finish(self) -> None:
        """Знакомство пройдено или пропущено — второй раз само не откроется."""
        config.save_section("ui", {"onboarded": True})
        if self._store is not None:
            self._store.set("ui", "onboarded", True)
        try:
            self._bridge.event.disconnect(self._forward)
        except (RuntimeError, TypeError):
            pass
        self.closed.emit()
        self.close()

    # ---------------------------------------------------------------- связь со страницей

    def _on_ready(self) -> None:
        self._live = True
        cfg = config.load()
        profile = {
            "voices": [
                {"key": item.key, "title": item.title, "character": item.character, "gender": item.gender}
                for item in voices.catalog()
            ],
            "voice": getattr(self._assistant, "voice_key", voices.DEFAULT),
            "name": str(cfg.get("account", {}).get("name", "")).strip(),
        }
        self.link.profile.emit(json.dumps(profile, ensure_ascii=False))

    def _forward(self, payload: dict) -> None:
        if not self._live:
            return
        text = event_json(payload)
        if text is not None:
            self.link.event.emit(text)

    def _say(self, text: str) -> None:
        threading.Thread(target=self._assistant.say, args=(text,), name="jarvis-onboarding-say",
                         daemon=True).start()

    def _preview(self, key: str) -> None:
        threading.Thread(target=self._assistant.preview_voice, args=(key,),
                         name="jarvis-onboarding-preview", daemon=True).start()

    def _choose_voice(self, key: str) -> None:
        if self._store is not None:
            self._store.set("tts", "voice", key)
        threading.Thread(target=self._assistant.set_voice, args=(key,),
                         name="jarvis-onboarding-voice", daemon=True).start()

    def _set_name(self, name: str) -> None:
        clean = name.strip()[:40]
        if not clean:
            return
        config.save_section("account", {"name": clean})
        if self._store is not None:
            self._store.set("account", "name", clean)
        agent = getattr(self._assistant, "_agent", None)
        if agent is not None:
            agent._cfg["owner"] = clean  # модель обращается по имени уже со следующей реплики

    # ---------------------------------------------------------------- проверки

    def _emit_check(self, **item: Any) -> None:
        self._check_ready.emit(json.dumps([item], ensure_ascii=False))

    def _run_checks(self) -> None:
        for job in (self._check_model, self._check_mic, self._check_voice, self._check_eyes):
            threading.Thread(target=self._safe, args=(job,), name="jarvis-onboarding-check", daemon=True).start()

    def _safe(self, job) -> None:
        try:
            job()
        except Exception as err:  # проверка не должна ронять окно знакомства
            bus.bus.log("error", f"проверка: {err}")

    def _check_model(self) -> None:
        from core import ollama_guard

        agent = self._assistant._agent
        if not agent.available(refresh=True):
            self._emit_check(id="model", title="Мозг на видеокарте", state="bad",
                             detail="Ollama не отвечает.", fix="Запусти Ollama из меню «Пуск» и нажми «Назад» → «Дальше».")
            return
        url = str(agent.url)
        verdict = ollama_guard.check(url)
        if verdict == "unknown":
            agent.warmup()
            verdict = ollama_guard.check(url)
        if verdict == "cpu":
            self._emit_check(id="model", title="Мозг на видеокарте", state="warn",
                             detail="Модель считается на процессоре — перезапускаю Ollama…")
            if ollama_guard.restart(url):
                agent.available(refresh=True)
                agent.warmup()
                verdict = ollama_guard.check(url)
        if verdict == "gpu":
            sees = " — и видит картинки" if agent.sees else ""
            self._emit_check(id="model", title="Мозг на видеокарте", state="ok",
                             detail=f"{agent.model} на видеокарте{sees}.")
        else:
            self._emit_check(id="model", title="Мозг на видеокарте", state="warn",
                             detail=f"{agent.model}: не удалось подтвердить работу на видеокарте.",
                             fix="Если ответы медленные — перезапусти Ollama из трея.")

    def _check_mic(self) -> None:
        from core import audio

        mic = getattr(self._assistant, "_mic", None)
        note = str(getattr(mic, "device_note", "") or "")
        device = note.split(" (")[0] if note else "микрофон"
        if audio.AUDIO_STUCK_NOTE in note:
            self._emit_check(id="mic", title="Микрофон", state="bad", detail="Звуковая система Windows не отвечает.",
                             fix="Перезапусти службу «Windows Audio» или компьютер.")
            return
        if bool(getattr(self._assistant, "_muted", None) and self._assistant._muted.is_set()):
            self._emit_check(id="mic", title="Микрофон", state="warn", device=device,
                             detail="Микрофон выключен в Юки.", fix="Включи его кнопкой микрофона в «Диалоге».")
            return
        self._emit_check(id="mic", title="Микрофон", state="wait", device=device,
                         detail=f"{device} — скажи что-нибудь вслух.")

    def _check_voice(self) -> None:
        voice = getattr(self._assistant, "_voice", None)
        engine = getattr(voice, "engine_name", "") if voice is not None else ""
        if engine != "edge":
            self._emit_check(id="voice", title="Голос", state="ok",
                             detail="Офлайн-голос: работает без интернета.")
            return
        import asyncio

        import edge_tts

        profile = voices.get(getattr(self._assistant, "voice_key", "")) or voices.get(voices.DEFAULT)

        async def first_audio() -> float:
            started = time.monotonic()
            async for item in edge_tts.Communicate("Проверка.", profile.edge_voice).stream():
                if item["type"] == "audio":
                    return time.monotonic() - started
            raise RuntimeError("пусто")

        try:
            spent = asyncio.run(asyncio.wait_for(first_audio(), 8))
        except Exception:
            self._emit_check(id="voice", title="Голос", state="warn",
                             detail="Нейроголос не ответил — буду говорить офлайн-голосом.",
                             fix="Нужен интернет. Если включён VPN, пусти speech.platform.bing.com мимо него.")
            return
        if spent > 2.5:
            self._emit_check(id="voice", title="Голос", state="warn",
                             detail=f"{profile.title}: первый звук через {spent:.1f} с — сеть медленная.",
                             fix="Ответы будут с паузой. Если включён VPN — пусти голос мимо него.")
        else:
            self._emit_check(id="voice", title="Голос", state="ok",
                             detail=f"{profile.title}: первый звук через {spent:.1f} с.")

    def _check_eyes(self) -> None:
        from core import ocr

        if not ocr.warmup():
            self._emit_check(id="eyes", title="Зрение", state="warn",
                             detail="Распознавание текста Windows недоступно.",
                             fix="Добавь русский язык в «Параметры → Время и язык».")
            return
        agent = self._assistant._agent
        extra = " и понимаю картинки" if getattr(agent, "sees", False) else ""
        self._emit_check(id="eyes", title="Зрение", state="ok",
                         detail=f"Читаю текст экрана за доли секунды{extra}.")
