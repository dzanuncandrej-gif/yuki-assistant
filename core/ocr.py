"""Распознавание текста на экране встроенным OCR Windows.

Зачем, если есть дерево интерфейса: браузерные страницы, игры, видео с
субтитрами, картинки, окна на Electron и холсты дерево показывает скупо или
никак. Модель зрения их видит, но она занимает видеопамять и выталкивает
языковую модель — каждый такой взгляд стоил секунды на перезагрузку весов.

OCR Windows работает на процессоре за доли секунды, подписан Microsoft (его не
блокирует «Умная защита приложений») и отдаёт не только текст, но и точные
прямоугольники строк — по ним можно даже нажимать.

Сам распознаватель живёт в постоянном процессе PowerShell (`ocr_server.ps1`):
запуск WinRT стоит около секунды, и платить её на каждом кадре нельзя.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).with_name("ocr_server.ps1")
_START_TIMEOUT_S = 12.0
_REQUEST_TIMEOUT_S = 8.0
# Меньше — быстрее, но мелкий текст интерфейса уже не читается. 1920 по длинной
# стороне — родное разрешение большинства экранов, дальше уменьшать не стоит.
MAX_SIDE = 1920


class OcrError(RuntimeError):
    """Распознавание недоступно или не ответило."""


@dataclass(frozen=True)
class Line:
    text: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom в пикселях экрана

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.rect
        return (left + right) // 2, (top + bottom) // 2


@dataclass(frozen=True)
class Reading:
    lines: tuple[Line, ...]
    at: float
    spent_ms: float

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def compact(self, limit: int = 1800) -> str:
        """Текст экрана одной выжимкой: без дублей и мусора из одиночных символов."""
        seen: set[str] = set()
        out: list[str] = []
        total = 0
        for line in self.lines:
            clean = line.text.strip()
            if len(clean) < 2 or clean.lower() in seen:
                continue
            seen.add(clean.lower())
            out.append(clean)
            total += len(clean) + 3
            if total >= limit:
                break
        return " | ".join(out)


class _Server:
    """Постоянный процесс OCR. Один запрос за раз, при сбое — перезапуск."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._broken_until = 0.0
        self.languages: tuple[str, ...] = ()

    def _start(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(_SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, creationflags=flags,
        )
        self._lines = queue.Queue()
        proc = self._proc

        def pump() -> None:
            for raw in proc.stdout:  # type: ignore[union-attr]
                self._lines.put(raw)
            self._lines.put("")

        threading.Thread(target=pump, name="jarvis-ocr-read", daemon=True).start()
        hello = self._read(_START_TIMEOUT_S)
        if not hello.get("ready"):
            raise OcrError("OCR Windows не запустился")
        self.languages = tuple(hello.get("languages") or ())
        if not self.languages:
            raise OcrError("в Windows не установлен язык распознавания текста")

    def _read(self, timeout: float) -> dict[str, Any]:
        try:
            raw = self._lines.get(timeout=timeout)
        except queue.Empty as err:
            raise OcrError("OCR не ответил вовремя") from err
        if not raw:
            raise OcrError("процесс OCR завершился")
        # PowerShell иногда ставит BOM в начало первой строки
        return json.loads(raw.lstrip("﻿"))

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    def request(self, path: str, language: str) -> dict[str, Any]:
        return self.send(f"{path}|{language}")

    def send(self, line: str) -> dict[str, Any]:
        with self._lock:
            if time.monotonic() < self._broken_until:
                raise OcrError("OCR временно недоступен")
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._start()
                assert self._proc is not None and self._proc.stdin is not None
                self._proc.stdin.write(f"{line}\n")
                self._proc.stdin.flush()
                return self._read(_REQUEST_TIMEOUT_S)
            except (OSError, ValueError, OcrError) as err:
                self._stop()
                self._broken_until = time.monotonic() + 30.0
                raise OcrError(str(err) or "OCR недоступен") from err


_server = _Server()


def available() -> bool:
    return os.name == "nt" and _SCRIPT.is_file()


def read_image(image: Any, origin: tuple[int, int] = (0, 0), language: str = "ru") -> Reading:
    """Распознаёт PIL-картинку. `origin` — где её левый верхний угол на экране."""
    if not available():
        raise OcrError("OCR работает только в Windows")
    started = time.monotonic()
    picture = image.convert("RGB")
    scale = 1.0
    if max(picture.size) > MAX_SIDE:
        scale = MAX_SIDE / max(picture.size)
        picture = picture.resize((int(picture.width * scale), int(picture.height * scale)))
    fd, name = tempfile.mkstemp(prefix="yuki-ocr-", suffix=".bmp")
    os.close(fd)
    try:
        picture.save(name, format="BMP")  # без сжатия: кодировать PNG дольше, чем распознавать
        reply = _server.request(name, language)
    finally:
        try:
            os.remove(name)
        except OSError:
            pass
    if not reply.get("ok"):
        raise OcrError(str(reply.get("error") or "OCR не справился"))
    ox, oy = origin
    lines = []
    for row in reply.get("lines") or ():
        text = str(row.get("t") or "").strip()
        rect = row.get("r") or (0, 0, 0, 0)
        if not text:
            continue
        left, top, right, bottom = (int(v / scale) for v in rect)
        lines.append(Line(text=_tidy(text), rect=(left + ox, top + oy, right + ox, bottom + oy)))
    return Reading(lines=tuple(lines), at=time.monotonic(), spent_ms=(time.monotonic() - started) * 1000)


def read_screen(region: tuple[int, int, int, int] | None = None) -> Reading:
    """Снимок экрана (или его части) и распознанный на нём текст."""
    from . import screen

    shot = screen.capture(region)
    return read_image(shot.image, origin=(shot.region[0], shot.region[1]))


# OCR Windows ставит пробелы между кириллическими буквами одного слова реже,
# чем между словами, но иногда лишний пробел перед знаком препинания остаётся.
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.:;!?)])")


def _tidy(text: str) -> str:
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def find(query: str, reading: Reading) -> Line | None:
    """Строка экрана, которая лучше всего совпадает с запросом, или None."""
    needle = _normalize(query)
    if len(needle) < 2:
        return None
    best: tuple[float, Line] | None = None
    for line in reading.lines:
        hay = _normalize(line.text)
        if not hay:
            continue
        if hay == needle:
            score = 1.0
        elif needle in hay:
            score = 0.8 + 0.2 * len(needle) / len(hay)
        else:
            words = set(needle.split())
            overlap = len(words & set(hay.split())) / max(1, len(words))
            score = overlap * 0.75
        if score >= 0.75 and (best is None or score > best[0]):
            best = (score, line)
    return best[1] if best else None


def _normalize(text: str) -> str:
    return re.sub(r"[^\w ]", " ", text.lower().replace("ё", "е")).strip()


def warmup() -> bool:
    """Поднимает процесс OCR заранее, чтобы первый вопрос про экран не ждал секунду."""
    if not available():
        return False
    try:
        with _server._lock:
            if _server._proc is None or _server._proc.poll() is not None:
                _server._start()
        return True
    except (OSError, OcrError):
        return False


def media(action: str) -> dict[str, Any]:
    """Медиасессия Windows: next | previous | play_pause | info. Ответ — что играло до и после."""
    if not available():
        raise OcrError("медиасессии доступны только в Windows")
    return _server.send(f"media|{action}")
