"""Режим видеозвонка: Юки постоянно смотрит на экран и слушает.

Три правила, ради которых всё переписано:

1. Кадры не ставятся в очередь. Наблюдатель держит только последний кадр, а интерфейс
   сам забирает его когда готов. Очередь старых кадров физически не может накопиться,
   поэтому картинка не «уезжает» и память не растёт.
2. Захват экрана самовосстанавливается. Смена разрешения, блокировка, RDP — mss ломается
   молча и навсегда; здесь после ошибки грабер пересоздаётся.
3. Модель зрения будится сменой сцены, а не таймером, и никогда не запускается второй раз
   поверх незавершённого разбора.
"""

from __future__ import annotations

import base64
import io
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from . import bus, vision

# вопросы, ради которых нужно посмотреть на экран прямо сейчас
SCREEN_QUESTIONS = re.compile(
    r"(что\s+(?:ты\s+)?(?:видишь|тут|здесь|на\s+экране|происходит|показано|написано|за\s+ошибка)|"
    r"что\s+это|как\s+это\s+(?:сделать|исправить|починить|работает)|что\s+(?:мне\s+)?(?:делать|исправить|"
    r"нажать|выбрать)|объясни(?:\s+что)?|прочитай(?:\s+это)?|переведи(?:\s+это)?|посмотри|"
    r"what\s+do\s+you\s+see|what.s\s+this|explain\s+this|read\s+this)",
    re.IGNORECASE,
)

DEFAULT_PROMPT = (
    "Опиши коротко, что сейчас на экране: приложение, чем занят человек, "
    "видимые ошибки или важный текст. Одно-два предложения по-русски."
)

# признаки того, что человеку стоит помочь, не дожидаясь вопроса
TROUBLE = re.compile(
    r"\b(ошибк\w*|error|exception|traceback|failed|не\s+удалось|отказано|denied|"
    r"предупрежд\w*|warning|сбой|краш|crash|синий\s+экран|не\s+отвечает|"
    r"обновлени\w*\s+доступн\w*|мало\s+места|заканчивается\s+место)\b",
    re.IGNORECASE,
)

# насколько кадры должны разойтись, чтобы считать это новой сценой (из 256 бит)
CHANGE_BITS = 14


@dataclass
class Frame:
    """Последний разобранный кадр экрана."""

    caption: str = ""
    image: bytes = b""
    at: float = 0.0
    error: str = ""

    @property
    def age(self) -> float:
        return time.monotonic() - self.at if self.at else 1e9

    @property
    def thumbnail(self) -> str:
        return base64.b64encode(self.image).decode("ascii") if self.image else ""


@dataclass
class Stats:
    """Показатели конвейера — их видно в интерфейсе звонка."""

    fps: float = 0.0
    capture_ms: float = 0.0
    analyses: int = 0
    analysis_ms: float = 0.0
    errors: int = 0
    last_error: str = ""
    healthy: bool = True

    def as_line(self) -> str:
        state = "норма" if self.healthy else "сбой"
        return (
            f"{self.fps:.0f} к/с · захват {self.capture_ms:.0f} мс · "
            f"разбор {self.analysis_ms / 1000:.1f} с · {state}"
        )


class Watcher:
    """Живой взгляд на экран: превью в реальном времени и разбор по изменению сцены."""

    def __init__(
        self,
        ollama_url: str,
        preview_fps: float = 8.0,
        min_gap_s: float = 2.0,
        idle_refresh_s: float = 30.0,
        preview_side: int = 640,
        analyze_side: int = 512,
    ) -> None:
        self.ollama_url = ollama_url
        self.preview_fps = max(1.0, float(preview_fps))
        self.min_gap_s = float(min_gap_s)
        self.idle_refresh_s = float(idle_refresh_s)
        self.preview_side = int(preview_side)
        self.analyze_side = int(analyze_side)

        self.frame = Frame()
        self.stats = Stats()
        self.on_frame: Callable[[Frame], None] | None = None

        # последний кадр держим как есть: интерфейс забирает его сам, когда успевает
        self.preview: bytes = b""
        self.preview_id = 0

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._analysis_lock = threading.Lock()
        self._busy = threading.Event()
        self._grabber = threading.local()
        self._signature: bytes = b""
        self._changed = threading.Event()
        self._last_analysis = 0.0
        self._backoff = 0.0

    # ---------------------------------------------------------------- жизненный цикл

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        self._changed.set()  # первый разбор сразу, не дожидаясь изменений
        threads = (
            (self._preview_loop, "jarvis-preview"),
            (self._analysis_loop, "jarvis-vision"),
            (self._warmup, "jarvis-vision-warmup"),
        )
        for target, name in threads:
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        self._changed.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads = []
        self._release_grabber()

    @property
    def running(self) -> bool:
        return bool(self._threads) and not self._stop.is_set()

    def _warmup(self) -> None:
        """Первый запрос к модели зрения самый долгий — делаем его заранее и молча."""
        model = vision.available_model(self.ollama_url)
        if model is None or self._stop.is_set():
            return
        try:
            vision.describe(
                self.grab(side=256), self.ollama_url, model, "hi", timeout_s=90,
                num_predict=1, keep_alive=vision.LIVE_KEEP_ALIVE,
            )
        except Exception:
            pass

    # ---------------------------------------------------------------- захват

    def _sct(self):
        """Свой захватчик на поток: mss не переносится между потоками."""
        grabber = getattr(self._grabber, "sct", None)
        if grabber is None:
            import mss

            grabber = mss.mss()
            self._grabber.sct = grabber
        return grabber

    def _release_grabber(self) -> None:
        """После ошибки грабер нужно пересоздать: сам он не оживает."""
        grabber = getattr(self._grabber, "sct", None)
        self._grabber.sct = None
        if grabber is not None:
            try:
                grabber.close()
            except Exception:
                pass

    def _shot(self, side: int, quality: int = 70) -> tuple[bytes, Any]:
        """Кадр экрана как JPEG плюс уменьшенная картинка для сравнения."""
        from PIL import Image

        grabber = self._sct()
        monitor = grabber.monitors[1]
        raw = grabber.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.rgb)
        image.thumbnail((side, side))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue(), image

    @staticmethod
    def _signature_of(image: Any) -> bytes:
        """Отпечаток кадра: 16×16 в оттенках серого, разностный хэш."""
        small = image.convert("L").resize((17, 16))
        pixels = small.load()
        bits = bytearray()
        for y in range(16):
            for x in range(16):
                bits.append(1 if pixels[x, y] > pixels[x + 1, y] else 0)
        return bytes(bits)

    @staticmethod
    def _distance(left: bytes, right: bytes) -> int:
        if not left or not right or len(left) != len(right):
            return 10_000
        return sum(1 for a, b in zip(left, right) if a != b)

    def grab(self, side: int | None = None) -> bytes:
        """Снимок для разбора моделью зрения."""
        image, _ = self._shot(side or self.analyze_side, quality=72)
        return image

    # ---------------------------------------------------------------- быстрый цикл

    def _preview_loop(self) -> None:
        period = 1.0 / self.preview_fps
        failures = 0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                jpeg, image = self._shot(self.preview_side, quality=60)
                failures = 0
            except Exception as err:
                failures += 1
                self.stats.errors += 1
                self.stats.last_error = f"захват: {err.__class__.__name__}"
                self.stats.healthy = failures < 3
                self._release_grabber()  # пересоздадим на следующем круге
                self._stop.wait(min(2.0, 0.25 * failures))
                continue

            spent = time.monotonic() - started
            self.preview = jpeg
            self.preview_id += 1
            self.stats.capture_ms = spent * 1000.0
            self.stats.fps = 1.0 / max(spent, 1e-3)
            self.stats.healthy = True

            try:
                signature = self._signature_of(image)
            except Exception:
                signature = b""
            if signature and self._distance(signature, self._signature) > CHANGE_BITS:
                self._signature = signature
                self._changed.set()  # сцена сменилась — будим зрение

            self._stop.wait(max(0.0, period - (time.monotonic() - started)))

    # ---------------------------------------------------------------- разбор сценой

    def _analysis_loop(self) -> None:
        while not self._stop.is_set():
            triggered = self._changed.wait(timeout=self.idle_refresh_s)
            if self._stop.is_set():
                return
            self._changed.clear()

            if self._backoff > time.monotonic():
                continue  # модель недавно ответила ошибкой — не бомбим её
            gap = time.monotonic() - self._last_analysis
            if triggered and gap < self.min_gap_s:
                self._stop.wait(self.min_gap_s - gap)
                if self._stop.is_set():
                    return
            if self._busy.is_set():
                continue  # предыдущий разбор ещё идёт — второй запускать бессмысленно
            if self._wait_until_free():
                continue  # человек говорит с ней — видеокарта сейчас нужна ответу
            try:
                self.refresh()
            except Exception as err:
                self.frame = Frame(error=str(err), at=time.monotonic())

    # ---------------------------------------------------------------- модель зрения

    def _wait_until_free(self, limit_s: float = 12.0) -> bool:
        """Ждёт, пока ассистент думает или говорит. True — так и не дождались.

        Модель зрения и языковая модель не помещаются в память видеокарты вместе:
        разбор кадра, запущенный посреди ответа, выгружает языковую модель, и
        человек ждёт её обратной загрузки — несколько секунд на каждой реплике.
        Экран никуда не денется, а разговор ждать не должен.
        """
        deadline = time.monotonic() + limit_s
        while bus.bus.state in (bus.THINKING, bus.SPEAKING):
            if self._stop.wait(0.4) or time.monotonic() > deadline:
                return True
        return False

    def refresh(self, prompt: str = DEFAULT_PROMPT, timeout_s: float = 45.0, words: int = 70) -> Frame:
        """Снимает экран и описывает его. Вызовы не наслаиваются друг на друга."""
        with self._analysis_lock:
            self._busy.set()
            started = time.monotonic()
            self._last_analysis = started
            try:
                image = self.grab()
                model = vision.available_model(self.ollama_url)
                if model is None:
                    frame = Frame(image=image, at=time.monotonic(), error="модель зрения не установлена")
                    self._backoff = time.monotonic() + 20.0
                else:
                    try:
                        caption = vision.describe(
                            image,
                            self.ollama_url,
                            model,
                            vision._prompt_for(model, prompt),
                            timeout_s,
                            num_predict=words,
                            keep_alive=vision.LIVE_KEEP_ALIVE,
                        )
                        frame = Frame(caption=caption.strip(), image=image, at=time.monotonic())
                        self.stats.analyses += 1
                        self.stats.analysis_ms = (time.monotonic() - started) * 1000.0
                        self._backoff = 0.0
                    except (vision.VisionError, requests.RequestException) as err:
                        frame = Frame(image=image, at=time.monotonic(), error=str(err)[:160])
                        self.stats.errors += 1
                        self.stats.last_error = str(err)[:120]
                        self._backoff = time.monotonic() + 8.0
            finally:
                self._busy.clear()
            self.frame = frame

        if self.on_frame is not None:
            self.on_frame(frame)
        # в шину уходит только текст: картинку интерфейс забирает сам, без очередей
        bus.bus.publish({"type": "vision", "caption": frame.caption or frame.error, "at": frame.at})
        return frame

    def ask(self, question: str, timeout_s: float = 45.0) -> str:
        """Вопрос про экран: всегда свежий снимок, ответ по-русски."""
        prompt = (
            f"{question.strip()} Отвечай кратко и по делу, двумя предложениями, по-русски. "
            "Опирайся только на то, что реально видно на экране."
        )
        frame = self.refresh(prompt=prompt, timeout_s=timeout_s, words=140)
        if frame.error and not frame.caption:
            raise vision.VisionError(frame.error)
        return frame.caption

    def context(self, max_age_s: float = 40.0) -> str:
        """Что сейчас на экране — для подсказки языковой модели.

        Сначала берётся структура: окно, кнопки, текст. Она всегда свежая, стоит
        сотую долю секунды и не врёт. Описание от модели зрения добавляется только
        как дополнение и только пока не устарело: оно про смысл картинки, но между
        разборами проходят десятки секунд, и окно за это время могло смениться.
        """
        parts: list[str] = []
        try:
            from . import screen

            parts.append(screen.scene().summary(limit=10))
        except Exception:
            pass
        frame = self.frame
        if frame.caption and frame.age <= max_age_s:
            parts.append(f"Картина экрана: {frame.caption}")
        return " ".join(parts)


def wants_screen(text: str) -> bool:
    """Вопрос относится к тому, что видно на экране."""
    return bool(SCREEN_QUESTIONS.search(str(text or "")))


def looks_like_trouble(caption: str) -> bool:
    """Похоже ли увиденное на проблему, о которой стоит сказать первым."""
    return bool(TROUBLE.search(str(caption or "")))


@dataclass
class CallLog:
    """Что происходило в звонке: реплики и увиденные сцены. Нужен для итога."""

    started: float = field(default_factory=time.monotonic)
    lines: list[str] = field(default_factory=list)
    scenes: list[str] = field(default_factory=list)

    def say(self, who: str, text: str) -> None:
        clean = str(text or "").strip()
        if clean:
            self.lines.append(f"{who}: {clean}")
            del self.lines[:-40]

    def saw(self, caption: str) -> None:
        clean = str(caption or "").strip()
        if clean and (not self.scenes or clean != self.scenes[-1]):
            self.scenes.append(clean)
            del self.scenes[:-20]

    @property
    def minutes(self) -> float:
        return (time.monotonic() - self.started) / 60.0

    def digest(self) -> str:
        """Сжатая выжимка разговора для языковой модели."""
        parts = []
        if self.lines:
            parts.append("Разговор:\n" + "\n".join(self.lines[-16:]))
        if self.scenes:
            parts.append("Что было на экране:\n" + "\n".join(f"- {scene}" for scene in self.scenes[-6:]))
        return "\n\n".join(parts)
