"""Синтез речи потоком: первая фраза звучит, пока синтезируется следующая.

Движки: Piper (локальный, по умолчанию, отдаёт аудио по предложениям), Edge-TTS
(нейроголос, нужен интернет), SAPI5 (запасной системный). Все отдают одинаковые куски
float32 mono, которые обрабатываются voicefx и уходят в звуковую карту без файлов.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import io
import os
import queue
import re
import sys
import tempfile
import threading
import time
import uuid
import wave
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from . import config, voicefx, voices

Chunk = tuple[np.ndarray, int]  # (сэмплы float32 mono, частота дискретизации)
LevelCallback = Callable[[float], None]
StopCheck = Callable[[], bool]

_MALE_HINTS = ("dmitri", "dmitry", "ruslan", "aidar", "male", "мужск", "pavel", "maxim", "artemiy")

# длина куска для синтеза: слишком короткие рвут интонацию, длинные тормозят старт
_MIN_CHUNK = 60
_MAX_CHUNK = 240
# первый кусок держим коротким — с него начинается звук, и его ждёт человек
_FIRST_CHUNK = 70
_MIN_FIRST = 18

_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")

# столько секунд не трогаем упавший движок (нет сети, заблокированная библиотека)
_BLOCK_S = 180.0
# короткие ответы («Готово.», «Слушаю.») кэшируются на диск и звучат мгновенно
_CACHE_LIMIT = 120
_CACHE_FILES = 240  # столько файлов держим в кэше, лишние удаляются


# модель Silero держим одну на процесс: она содержит всех дикторов сразу
_silero_model: Any | None = None
_silero_lock = threading.Lock()

# Silero читает латиницу побуквенно, поэтому редкие английские вкрапления убираем
_LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9\-]{1,}\b")
_TRANSLIT = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
    "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
    "y": "й", "z": "з",
}


def _for_silero(text: str) -> str:
    """Латинские слова переводим в кириллицу: иначе они читаются по буквам."""

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        return "".join(_TRANSLIT.get(char.lower(), char) for char in word)

    return _LATIN_WORD.sub(replace, text)


class SynthesisError(RuntimeError):
    pass


# Реплики, которые звучат чаще всего. Их синтез заготавливается при запуске:
# короткое слово в начале ответа не должно стоить секунды ожидания.
COMMON_PHRASES: tuple[str, ...] = (
    "Готово.", "Секунду.", "Слушаю.", "Ага.", "Хорошо.", "Сделала.", "Конечно!",
    "Привет!", "Минутку.", "Не поняла, повтори?", "Сейчас посмотрю.", "Открываю.",
    "Юки на связи.", "Отменила.", "Да?", "Уже делаю.",
)


def split_for_speech(text: str) -> tuple[str, ...]:
    """Режет текст на куски по границам предложений — их можно синтезировать по очереди.

    Первый кусок делается коротким намеренно: чем меньше текста, тем быстрее вернётся
    синтез, и человек слышит ответ раньше. Остальные куски догоняют, пока звучит первый.
    """
    pieces = [piece.strip() for piece in _SENTENCE.split(text.strip()) if piece.strip()]
    if not pieces:
        return ()

    head = pieces[0]
    if len(head) > _FIRST_CHUNK:
        cut = max(head.rfind(", ", 0, _FIRST_CHUNK), head.rfind(" — ", 0, _FIRST_CHUNK))
        if cut < _MIN_FIRST:
            cut = head.rfind(" ", 0, _FIRST_CHUNK)
        if cut >= _MIN_FIRST:
            pieces = [head[:cut].strip(" ,—"), head[cut:].strip(" ,—"), *pieces[1:]]

    chunks: list[str] = []
    buffer = ""
    for index, piece in enumerate(pieces):
        while len(piece) > _MAX_CHUNK:
            cut = piece.rfind(", ", 0, _MAX_CHUNK)
            cut = cut if cut > _MIN_CHUNK else _MAX_CHUNK
            chunks.append(piece[:cut].strip())
            piece = piece[cut:].strip(" ,")
        candidate = f"{buffer} {piece}".strip()
        # порог первого куска действует, пока не отдан ни один кусок. Условие по
        # номеру предложения не годилось: «Привет.» короче порога, уходило в
        # буфер, и дальше уже работал большой порог — весь ответ синтезировался
        # разом, а человек ждал первого звука до конца синтеза
        limit = _MIN_FIRST if not chunks else _MIN_CHUNK
        if len(candidate) < limit:
            buffer = candidate
            continue
        chunks.append(candidate)
        buffer = ""
    if buffer:
        chunks.append(buffer)
    return tuple(chunks)


# потоковая нарезка: с чего можно начинать синтез, не дожидаясь конца ответа
_STREAM_ENDS = ".!?…\n"
_STREAM_SOFT = ",;:—"
# первый кусок отдаём как можно раньше — с него начинается звук
_STREAM_FIRST_MIN = 6
_STREAM_FIRST_SOFT = 26
_STREAM_MIN = 24
_STREAM_SOFT_AT = 80
_STREAM_HARD = 190


def _speakable_cut(buffer: str, first: bool) -> int | None:
    """Где кончается кусок, который уже можно озвучивать. None — текста ещё мало.

    Первый кусок отрезается заметно раньше остальных: пока он звучит, модель
    успевает дописать продолжение, и пауза между ними не слышна. Дальше куски
    берутся длиннее — так интонация внутри предложения не рвётся.
    """
    if not buffer.strip():
        return None
    low = _STREAM_FIRST_MIN if first else _STREAM_MIN
    soft_at = _STREAM_FIRST_SOFT if first else _STREAM_SOFT_AT

    for index, char in enumerate(buffer):
        if index + 1 < low:
            continue
        if char in _STREAM_ENDS:
            # «3.5» и «т.д.» — точка внутри слова, не конец предложения
            nxt = buffer[index + 1 : index + 2]
            if char == "." and nxt and not nxt.isspace():
                continue
            return index + 1
        if char in _STREAM_SOFT and index + 1 >= soft_at:
            return index + 1
    if len(buffer) >= _STREAM_HARD:
        cut = buffer.rfind(" ", 0, _STREAM_HARD)
        return cut + 1 if cut > low else _STREAM_HARD
    return None


def _short_path(path: Path) -> str:
    """Короткое 8.3-имя пути. Движок espeak-ng — сишный и не открывает пути с кириллицей."""
    if sys.platform != "win32":
        return str(path)
    buffer = ctypes.create_unicode_buffer(1024)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024)
    return buffer.value if length and buffer.value.isascii() else str(path)


def _prepare_espeak() -> None:
    """Указывает espeak-ng на его данные внутри пакета piper, обходя не-ASCII путь проекта."""
    import piper

    data_dir = Path(piper.__file__).resolve().parent / "espeak-ng-data"
    if data_dir.exists():
        os.environ.setdefault("ESPEAK_DATA_PATH", _short_path(data_dir))


class Speaker:
    """Синтез. Движок выбирается один раз, голос остаётся загруженным в память."""

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self._cfg = dict(cfg)
        self._tmp = Path(tempfile.gettempdir()) / "jarvis_tts"
        self._tmp.mkdir(parents=True, exist_ok=True)
        self._swap = threading.Lock()
        self._loaded: dict[str, Any] = {}  # путь модели → загруженный PiperVoice
        self._blocked: dict[str, float] = {}  # движок → до какого момента его не трогаем
        self._cache_dir = self._tmp / "cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._voice: Any | None = None
        self._profile: voices.Profile | None = None
        self._piper_model: Path | None = None
        self._fx: dict[str, float] = {}
        self._apply_profile(voices.current(self._cfg))
        self._engine_name = self._pick_engine()
        # выбранный движок помним отдельно: к нему возвращаемся, как только он оживёт
        self._preferred_engine = self._engine_name

    def _apply_profile(self, profile: voices.Profile | None) -> None:
        """Профиль задаёт модель и характер тембра. Не скачанный голос настройки не меняет."""
        if profile is not None and profile.installed:
            self._cfg.update(profile.overrides())
            self._profile = profile
        self._piper_model = config.resolve_path(self._cfg.get("piper_model"))
        preset = voicefx.settings(str(self._cfg.get("voice_preset", voicefx.DEFAULT_PRESET)))
        # любой параметр пресета можно переопределить в config.json ключом voice_<имя>
        self._fx = {key: float(self._cfg.get(f"voice_{key}", value)) for key, value in preset.items()}
        self._fx["gain"] = float(self._cfg.get("voice_gain", 1.0))

    @property
    def profile(self) -> voices.Profile | None:
        return self._profile

    def set_language(self, language: str, edge_voice: str | None = None) -> None:
        """Переключает язык синтеза: голос Edge/SAPI и приоритет движков.

        Silero и Piper здесь знают только русский (модели не английские), поэтому
        английский режим принудительно уходит на Edge — единственный движок, у
        которого голос меняется по языку без скачивания новой модели.
        """
        with self._swap:
            self._cfg["pyttsx3_voice_hint"] = "en" if language == "en" else "ru"
            if edge_voice:
                self._cfg["edge_voice"] = edge_voice
            if language == "en":
                # человек явно попросил английский — это и есть согласие на
                # Edge, gate по allow_cloud_voice здесь ни к чему
                self._cfg["engine"] = "edge"
                self._engine_name = self._preferred_engine = "edge"
            else:
                self._engine_name = self._preferred_engine = self._pick_engine()

    def preload(self) -> tuple[str, ...]:
        """Загружает остальные установленные голоса в память — переключение станет мгновенным."""
        if self._engine_name == "silero":
            self._silero  # noqa: B018 — одна модель на всех дикторов, грузим её заранее
            return tuple(profile.title for profile in voices.catalog())
        if self._engine_name != "piper":
            return ()
        from piper import PiperVoice

        _prepare_espeak()
        ready: list[str] = []
        for profile in voices.catalog():
            path = str(profile.model_path)
            if not profile.installed or path in self._loaded:
                continue
            settings = Path(f"{path}.json")
            try:
                loaded = PiperVoice.load(path, config_path=str(settings) if settings.exists() else None)
            except Exception:
                continue
            with self._swap:
                self._loaded[path] = loaded
                if self._voice is None and self._piper_model is not None and str(self._piper_model) == path:
                    self._voice = loaded
            ready.append(profile.title)
        return tuple(ready)

    def use(self, profile: voices.Profile) -> voices.Profile:
        """Переключает голос. У Silero это смена одной строки, у Piper — смена модели."""
        if not profile.installed:
            raise SynthesisError(
                f"голос {profile.title} не скачан. Выполни: "
                f"python scripts/download_voice_model.py"
            )
        with self._swap:
            if self._voice is not None and self._piper_model is not None:
                self._loaded[str(self._piper_model)] = self._voice
            self._apply_profile(profile)
            self._voice = self._loaded.get(str(self._piper_model))
            # Выбор движка человеком важнее модели профиля. Раньше здесь стояло
            # безусловное переключение на Piper, и заданный «edge» молча
            # терялся: нейронный голос Svetlana не звучал ни разу, хотя профиль
            # его и объявляет. Автовыбор ведёт себя как прежде.
            requested = str(self._cfg.get("engine", "auto")).strip().lower()
            promote = requested in ("", "auto") and self._engine_name not in ("silero", "edge")
            if promote and self._piper_available():
                # раньше модели не было, теперь есть
                self._engine_name = self._preferred_engine = "piper"
        return profile

    # ---------------------------------------------------------------- выбор движка

    def _piper_available(self) -> bool:
        if self._piper_model is None or not self._piper_model.exists():
            return False
        try:
            import piper  # noqa: F401
        except ImportError:
            return False
        return True

    def _edge_allowed(self) -> bool:
        """Edge-TTS отправляет текст ответа на сервер Microsoft — это не «локально».

        Разрешён без вопросов, если голос выбран явно (`engine: "edge"`). Как
        тихий автоматический запасной вариант — только если это отдельно включено
        в config.json (`tts.allow_cloud_voice`), а не всегда, как было раньше.
        """
        if str(self._cfg.get("engine", "auto")).lower() == "edge":
            return True
        return bool(self._cfg.get("allow_cloud_voice", False))

    def _edge_available(self) -> bool:
        if not self._edge_allowed():
            return False
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return True

    def _pick_engine(self) -> str:
        """Порядок: Silero (быстрый и живой), Piper (офлайн), Edge (сеть), SAPI (последний)."""
        requested = str(self._cfg.get("engine", "auto")).lower()
        if requested == "silero":
            if not self._silero_available():
                raise SynthesisError(
                    "Silero запрошен, но модель не скачана. Запусти: "
                    "python scripts/download_voice_model.py"
                )
            return "silero"
        if requested == "piper":
            if not self._piper_available():
                raise SynthesisError(
                    f"Piper запрошен, но модель не найдена: {self._piper_model}. "
                    "Запусти scripts/download_piper_voice.py"
                )
            return "piper"
        if requested == "edge":
            if not self._edge_available():
                raise SynthesisError("Edge-TTS запрошен, но пакет edge-tts не установлен")
            return "edge"
        if requested == "pyttsx3":
            return "pyttsx3"
        if self._silero_available():
            return "silero"
        return "piper" if self._piper_available() else ("edge" if self._edge_available() else "pyttsx3")

    @property
    def engine_name(self) -> str:
        return self._engine_name

    # ---------------------------------------------------------------- потоковый синтез

    def stream(self, text: str, should_stop: StopCheck | None = None) -> Iterator[Chunk]:
        """Отдаёт куски речи по мере готовности. Первый кусок появляется за доли секунды."""
        from . import text as text_utils

        clean = text_utils.for_speech(text)
        if not clean:
            return
        yield from self._render(clean, should_stop)

    def stream_text(
        self, pieces: Iterator[str], should_stop: StopCheck | None = None
    ) -> Iterator[Chunk]:
        """Синтез по ходу генерации: модель ещё пишет ответ, а начало уже звучит.

        Куски текста приходят от языковой модели по мере готовности. Как только
        накопилось законченное предложение (или просто достаточно слов), оно
        уходит в синтез. Это убирает главную паузу разговора: раньше человек
        ждал, пока модель допишет ответ целиком, и только потом слышал первое слово.
        """
        from . import text as text_utils

        buffer = ""
        spoken = 0
        said = 0  # сколько символов уже прозвучало — по ним обрывается монолог
        for piece in pieces:
            if should_stop is not None and should_stop():
                return
            buffer += piece
            while True:
                cut = _speakable_cut(buffer, first=spoken == 0)
                if cut is None:
                    break
                head, buffer = buffer[:cut], buffer[cut:]
                clean = text_utils.for_speech(head)
                if clean:
                    yield from self._render(clean, should_stop)
                    spoken += 1
                    said += len(clean)
                # Предел длины реплики. Целый ответ раньше обрезался в `for_speech`,
                # но при потоковом синтезе туда попадает по одному предложению —
                # общая мера потерялась, и модель могла говорить монолог на полминуты.
                # Обрываем на границе предложения, как и раньше.
                if said >= text_utils.SPEECH_LIMIT:
                    return
        tail = text_utils.for_speech(buffer)
        if tail:
            yield from self._render(tail, should_stop)

    def _render(self, clean: str, should_stop: StopCheck | None) -> Iterator[Chunk]:
        """Один готовый кусок текста → звук. Здесь же кэш и подмена упавшего движка."""
        cached = self._cache_read(clean)
        if cached is not None:
            yield cached  # короткие частые фразы звучат мгновенно, без синтеза
            return

        # Предпочтительный движок пробуем первым, даже если сейчас работает
        # запасной. Иначе одна сетевая осечка Edge навсегда роняла сеанс на
        # локальный синтез: голос менялся посреди разговора и уже не возвращался,
        # хотя сеть восстанавливалась через полминуты.
        preferred = self._preferred_engine
        order = [preferred] + [
            e for e in (self._engine_name, "silero", "piper", "edge", "pyttsx3")
            if e != preferred
        ]
        order = list(dict.fromkeys(order))
        errors: list[str] = []
        collected: list[np.ndarray] = []
        retried = False        # вторая попытка предпочтительному движку
        index = 0
        while index < len(order):
            engine = order[index]
            index += 1
            if self._is_blocked(engine):
                continue
            if engine == "silero" and not self._silero_available():
                continue
            if engine == "piper" and not self._piper_available():
                continue
            if engine == "edge" and not self._edge_available():
                continue
            produced = False
            rate_used = 0
            try:
                for samples, rate in getattr(self, f"_stream_{engine}")(clean, should_stop):
                    if should_stop is not None and should_stop():
                        return
                    if samples.size == 0:
                        continue
                    produced = True
                    rate_used = rate
                    shaped = voicefx.shape(samples, rate, **self._fx)
                    collected.append(shaped)
                    yield shaped, rate
            except Exception as err:
                errors.append(f"{engine}: {err}")
                if produced:
                    return  # часть уже прозвучала, второй движок начнёт с начала — не надо
                # Предпочтительному движку даётся вторая попытка, и он не
                # объявляется мёртвым с первой осечки. Edge отвечает по сети:
                # один разорванный ответ посреди длинной реплики — обычное дело,
                # а последствия были грубые. Движок помечался упавшим, следующая
                # фраза читалась другим голосом, и человек слышал, как посреди
                # ответа сменился говорящий. Смена голоса хуже секундной паузы.
                if engine == preferred and not retried:
                    retried = True
                    time.sleep(0.35)
                    order.insert(index, engine)
                    continue
                self._block(engine, err)
                continue
            if produced:
                if engine != self._engine_name:
                    self._engine_name = engine  # запомним рабочий движок
                    self._note(f"синтез переключён на {engine}")
                self._cache_write(clean, collected, rate_used)
                return
        raise SynthesisError("; ".join(errors) or "ни один движок не дал звук")

    # ---------------------------------------------------------------- устойчивость

    def _is_blocked(self, engine: str) -> bool:
        """Движок, который только что упал, какое-то время не трогаем — иначе каждая
        фраза будет ждать одну и ту же ошибку (нет сети, заблокированная библиотека)."""
        return self._blocked.get(engine, 0.0) > time.monotonic()

    def _block(self, engine: str, error: Exception) -> None:
        self._blocked[engine] = time.monotonic() + _BLOCK_S
        reason = str(error)
        if "espeakbridge" in reason or "Политика управления" in reason or "application control" in reason.lower():
            reason = (
                "библиотеку Piper заблокировала «Умная защита приложений» Windows. "
                "Отключи Smart App Control в «Безопасность Windows → Управление приложениями и браузером» "
                "или пользуйся нейроголосом Edge (нужен интернет)"
            )
        self._note(f"движок {engine} недоступен: {reason[:200]}")

    def _note(self, message: str) -> None:
        """Сообщение в журнал интерфейса, если шина событий доступна."""
        try:
            from . import bus

            bus.bus.log("system", f"TTS: {message}")
        except Exception:
            pass

    def diagnose(self) -> str:
        """Короткая справка о движках — видна при запуске и по команде «проверь голос»."""
        parts = [f"активен {self._engine_name}"]
        parts.append("Silero готов" if self._silero_available() else "Silero не установлен")
        if self._piper_model is not None and not self._piper_model.exists():
            parts.append("модель Piper не скачана")
        try:
            import piper  # noqa: F401
            from piper import PiperVoice  # noqa: F401

            if self._piper_model is not None and self._piper_model.exists():
                self._piper_voice.phonemize("тест")
                parts.append("Piper готов")
        except Exception as err:
            parts.append(f"Piper недоступен ({str(err)[:80]})")
        parts.append("Edge доступен" if self._edge_available() else "Edge не установлен")
        return "; ".join(parts)

    # ---------------------------------------------------------------- кэш коротких фраз

    def _cache_key(self, text: str) -> str:
        profile = self._profile.key if self._profile is not None else "default"
        digest = hashlib.sha1(f"{profile}|{self._engine_name}|{text}".encode()).hexdigest()[:20]
        return f"{profile}_{digest}.wav"

    def _cache_read(self, text: str) -> Chunk | None:
        if len(text) > _CACHE_LIMIT:
            return None
        path = self._cache_dir / self._cache_key(text)
        if not path.exists():
            return None
        try:
            samples, rate = voicefx._read(path)
        except Exception:
            path.unlink(missing_ok=True)
            return None
        return samples, rate

    def _cache_write(self, text: str, chunks: list[np.ndarray], rate: int) -> None:
        if len(text) > _CACHE_LIMIT or not chunks or rate <= 0:
            return
        try:
            voicefx._write(self._cache_dir / self._cache_key(text), np.concatenate(chunks), rate)
            self._prune_cache()
        except Exception:
            pass

    def _prune_cache(self) -> None:
        """Кэш фраз не должен расти бесконечно: держим последние файлы, старые убираем."""
        files = sorted(self._cache_dir.glob("*.wav"), key=lambda item: item.stat().st_mtime)
        if len(files) <= _CACHE_FILES:
            return
        for path in files[: len(files) - _CACHE_FILES]:
            path.unlink(missing_ok=True)

    def synthesize(self, text: str) -> Path:
        """Целый WAV-файл — нужен для отладки и совместимости."""
        chunks = list(self.stream(text))
        if not chunks:
            raise SynthesisError("пустой текст для синтеза")
        rate = chunks[0][1]
        samples = np.concatenate([chunk for chunk, _ in chunks])
        target = self._tmp / f"{uuid.uuid4().hex}.wav"
        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes((np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes())
        return target

    # --- Silero ---

    @property
    def _silero(self) -> Any:
        """Модель Silero одна на все голоса: переключение диктора ничего не грузит."""
        global _silero_model
        with _silero_lock:
            if _silero_model is None:
                import torch

                # путь проекта кириллический, а сишный загрузчик torch открывает файлы
                # через ANSI — поэтому модель читаем в память и отдаём буфером
                with voices.SILERO_PATH.open("rb") as handle:
                    buffer = io.BytesIO(handle.read())
                model = torch.package.PackageImporter(buffer).load_pickle("tts_models", "model")
                model.to(torch.device("cpu"))
                torch.set_num_threads(max(2, min(8, (os.cpu_count() or 4))))
                _silero_model = model
            return _silero_model

    def _silero_available(self) -> bool:
        if not voices.silero_ready():
            return False
        try:
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def _stream_silero(self, text: str, should_stop: StopCheck | None) -> Iterator[Chunk]:
        model = self._silero
        speaker = str(self._cfg.get("silero_speaker", "aidar"))
        rate = int(self._cfg.get("silero_rate", 48000))
        for piece in split_for_speech(text):
            if should_stop is not None and should_stop():
                return
            try:
                audio = model.apply_tts(
                    text=_for_silero(piece), speaker=speaker, sample_rate=rate,
                    put_accent=True, put_yo=True,
                )
            except Exception as err:
                if "no supported" in str(err).lower() or not piece.strip(" .,!?"):
                    continue
                raise
            samples = audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio)
            yield np.asarray(samples, dtype=np.float32), rate

    # --- Piper ---

    @property
    def _piper_voice(self) -> Any:
        if self._voice is None:
            _prepare_espeak()
            from piper import PiperVoice

            model = str(self._piper_model)
            cached = self._loaded.get(model)
            if cached is not None:
                self._voice = cached
                return self._voice
            config_file = Path(f"{model}.json")
            self._voice = PiperVoice.load(model, config_path=str(config_file) if config_file.exists() else None)
            self._loaded[model] = self._voice
        return self._voice

    def _syn_config(self) -> Any:
        from piper import SynthesisConfig

        settings: dict[str, Any] = {
            "length_scale": float(self._cfg.get("piper_length_scale", 1.0)),
            "noise_scale": float(self._cfg.get("piper_noise_scale", 0.667)),
            "noise_w_scale": float(self._cfg.get("piper_noise_w", 0.8)),
            "volume": float(self._cfg.get("piper_volume", 1.0)),
        }
        speaker = self._cfg.get("piper_speaker")
        if speaker is not None:
            settings["speaker_id"] = int(speaker)
        return SynthesisConfig(**settings)

    def _stream_piper(self, text: str, should_stop: StopCheck | None) -> Iterator[Chunk]:
        voice = self._piper_voice
        config_obj = self._syn_config()
        for piece in split_for_speech(text):
            if should_stop is not None and should_stop():
                return
            for chunk in voice.synthesize(piece, syn_config=config_obj):
                audio = getattr(chunk, "audio_float_array", None)
                rate = int(getattr(chunk, "sample_rate", 22050))
                if audio is None:
                    raw = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
                    audio = raw.astype(np.float32) / 32768.0
                yield np.asarray(audio, dtype=np.float32), rate

    # --- Edge-TTS ---

    def _stream_edge(self, text: str, should_stop: StopCheck | None) -> Iterator[Chunk]:
        import edge_tts
        import soundfile as sf

        voice = str(self._cfg.get("edge_voice", "ru-RU-DmitryNeural"))
        rate = str(self._cfg.get("edge_rate", "+0%"))
        pitch = str(self._cfg.get("edge_pitch", "-10Hz"))

        async def render(piece: str) -> bytes:
            buffer = io.BytesIO()
            communicate = edge_tts.Communicate(piece, voice, rate=rate, pitch=pitch)
            async for item in communicate.stream():
                if item["type"] == "audio":
                    buffer.write(item["data"])
            return buffer.getvalue()

        for piece in split_for_speech(text):
            if should_stop is not None and should_stop():
                return
            raw = asyncio.run(render(piece))
            if not raw:
                continue
            samples, sample_rate = sf.read(io.BytesIO(raw), dtype="float32")
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            yield samples.astype(np.float32), int(sample_rate)

    # --- SAPI5 ---

    def _stream_pyttsx3(self, text: str, should_stop: StopCheck | None) -> Iterator[Chunk]:
        import pyttsx3

        for piece in split_for_speech(text):
            if should_stop is not None and should_stop():
                return
            target = self._tmp / f"{uuid.uuid4().hex}.wav"
            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", int(self._cfg.get("pyttsx3_rate", 180)))
                voice_id = self._pick_sapi_voice(engine)
                if voice_id:
                    engine.setProperty("voice", voice_id)
                engine.save_to_file(piece, str(target))
                engine.runAndWait()
            finally:
                engine.stop()
            if not target.exists() or target.stat().st_size == 0:
                continue
            try:
                samples, rate = voicefx._read(target)
                yield samples, rate
            finally:
                target.unlink(missing_ok=True)

    def _pick_sapi_voice(self, engine: Any) -> str | None:
        """Системный голос нужного языка. Чужой язык не подставляем.

        Раньше при отсутствии русского голоса брался любой: английский SAPI
        читал кириллицу по своим правилам, и речь превращалась в бессмыслицу.
        Случалось это не сразу — только когда основные движки успевали
        отвалиться и очередь доходила до системного.
        """
        hint = str(self._cfg.get("pyttsx3_voice_hint", "")).lower()
        voices = engine.getProperty("voices") or []
        by_lang = [v for v in voices if hint and hint in f"{v.id} {v.name}".lower()]
        if hint and not by_lang:
            raise SynthesisError(
                f"в системе нет голоса для «{hint}»: читать этот текст чужим голосом нельзя"
            )
        pool = by_lang or list(voices)
        for voice in pool:
            label = f"{voice.id} {voice.name}".lower()
            if any(mark in label for mark in _MALE_HINTS):
                return voice.id
        return pool[0].id if pool else None


class Voice:
    """Проигрывание речи: синтез в фоне, воспроизведение без пауз, мгновенное прерывание."""

    def __init__(self, cfg: Mapping[str, Any], device: int | str | None = None) -> None:
        self.speaker = Speaker(cfg)
        self._device = device
        self._busy = threading.Event()
        self._playback = threading.Lock()

    @property
    def engine_name(self) -> str:
        return self.speaker.engine_name

    @property
    def speaking(self) -> bool:
        return self._busy.is_set()

    @property
    def profile(self) -> voices.Profile | None:
        return self.speaker.profile

    def set_profile(self, name: str | voices.Profile) -> voices.Profile:
        """Переключает голос по имени («атлас») или по готовому профилю."""
        profile = name if isinstance(name, voices.Profile) else voices.resolve(str(name))
        return self.speaker.use(profile)

    def preload(self) -> tuple[str, ...]:
        return self.speaker.preload()

    def warmup(self) -> None:
        """Загружает голос и прогоняет короткую фразу без звука: первая реплика не ждёт модель."""
        try:
            for _ in self.speaker.stream("Готов."):
                break
        except Exception:
            pass

    def prime_cache(self, phrases: tuple[str, ...] = COMMON_PHRASES) -> int:
        """Синтезирует ходовые короткие реплики заранее и кладёт их в кэш.

        Нейроголос Edge живёт в сети: каждая фраза — это отдельное соединение и
        секунда-полторы ожидания. Именно она слышна как задержка перед ответом.
        Заготовленные заранее «ага», «секунду» и «готово» звучат мгновенно, и
        разговор перестаёт спотыкаться на самых частых словах.
        """
        ready = 0
        for phrase in phrases:
            try:
                for _ in self.speaker.stream(phrase):
                    pass
                ready += 1
            except Exception:
                continue
        return ready

    def say(
        self,
        text: str,
        should_stop: StopCheck | None = None,
        on_level: LevelCallback | None = None,
        on_viseme: Callable[[dict[str, float]], None] | None = None,
    ) -> bool:
        """Произносит текст. Возвращает False, если речь была прервана.

        Воспроизведение сериализовано: две реплики одновременно писали бы в один поток
        вывода и звучали кашей.
        """
        with self._playback:
            return self._say(
                lambda stop: self.speaker.stream(text, should_stop=stop),
                should_stop, on_level, on_viseme,
            )

    def say_stream(
        self,
        pieces: Iterator[str],
        should_stop: StopCheck | None = None,
        on_level: LevelCallback | None = None,
        on_viseme: Callable[[dict[str, float]], None] | None = None,
    ) -> bool:
        """Произносит ответ, который ещё пишется: речь начинается с первого предложения."""
        with self._playback:
            return self._say(
                lambda stop: self.speaker.stream_text(pieces, should_stop=stop),
                should_stop, on_level, on_viseme,
            )

    def _say(
        self,
        source: Callable[[StopCheck], Iterator[Chunk]],
        should_stop: StopCheck | None = None,
        on_level: LevelCallback | None = None,
        on_viseme: Callable[[dict[str, float]], None] | None = None,
    ) -> bool:
        from . import audio

        stop = should_stop or (lambda: False)
        # запас в четыре куска: синтез успевает уйти вперёд воспроизведения, и
        # между фразами не возникает паузы, пока считается следующая
        pending: queue.Queue[Chunk | None] = queue.Queue(maxsize=4)
        failure: list[Exception] = []

        def produce() -> None:
            try:
                for chunk in source(stop):
                    while not stop():
                        try:
                            pending.put(chunk, timeout=0.2)
                            break
                        except queue.Full:
                            continue
                    if stop():
                        break
            except Exception as err:
                failure.append(err)
            finally:
                try:
                    pending.put_nowait(None)
                except queue.Full:
                    pass

        self._busy.set()
        worker = threading.Thread(target=produce, name="jarvis-tts", daemon=True)
        worker.start()
        completed = True
        player: audio.Player | None = None
        try:
            while True:
                try:
                    item = pending.get(timeout=0.3)
                except queue.Empty:
                    if stop():
                        completed = False
                        break
                    if not worker.is_alive() and pending.empty():
                        break
                    continue
                if item is None:
                    break
                samples, rate = item
                if player is None:
                    # общий поток вывода: не открываем устройство на каждую реплику
                    player = audio.Player.shared(rate, device=self._device)
                if not player.write(samples, should_stop=stop, on_level=on_level,
                                    on_viseme=on_viseme):
                    completed = False
                    break
        finally:
            if player is not None and not completed:
                player.flush()  # оборванную речь сбрасываем, чтобы хвост не догонял
            self._busy.clear()
            if on_level is not None:
                on_level(0.0)
            if on_viseme is not None:
                on_viseme({"open": 0.0, "a": 0.0, "e": 0.0, "i": 0.0, "o": 0.0, "u": 0.0})
            worker.join(timeout=0.5)

        if failure and player is None:
            # ни один кусок не прозвучал — это настоящая ошибка синтеза
            raise SynthesisError(str(failure[0]))
        return completed
