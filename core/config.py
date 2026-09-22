"""Конфигурация: config.json поверх значений по умолчанию, плюс переменные окружения.

Секреты в config.json не хранятся. Значение вида "${OPENWEATHER_KEY}" подставляется
из окружения или из файла .env рядом с проектом.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

DEFAULTS: Mapping[str, Any] = {
    "audio": {
        "sample_rate": 16000,
        "block_ms": 30,
        "silence_ms": 620,
        "min_speech_ms": 260,
        "max_utterance_ms": 15000,
        "calibration_ms": 600,
        "vad_threshold_scale": 3.0,
        "vad_threshold_floor": 0.005,
        "neural_vad": True,     # детектор речи Silero вместо порога громкости
        "vad_start": 0.5,
        "vad_end": 0.3,
        "preroll_ms": 360,      # сколько звука до начала речи добавлять в реплику
        "barge_in_scale": 4.0,
        "barge_in_ms": 300,
        "auto_input": True,     # выбрать микрофон, который реально слышит
        "input_device": None,
        "output_device": None,
    },
    "stt": {
        "model_size": "small",
        "device": "cpu",                       # cuda — только если видеокарта свободна
        "gpu_model_size": "large-v3-turbo",
        "gpu_compute_type": "int8_float16",
        "compute_type": "int8",
        "language": "ru",
        "beam_size": 1,
        "vad_filter": False,
        "cpu_threads": 8,
        "no_speech_threshold": 0.55,
        "lexicon": True,        # исправление расслышанных слов по словарю команд
        "initial_prompt": "",
    },
    "tts": {
        "engine": "auto",
        "voice": "jarvis",  # профиль из core/voices.py: jarvis | atlas | aura
        "piper_model": "models/piper/ru_RU-dmitri-medium.onnx",
        "piper_speaker": None,
        "voice_preset": "deep",
        "voice_gain": 1.0,
        "pyttsx3_rate": 180,
        "pyttsx3_voice_hint": "ru",
        "allow_cloud_voice": False,  # тихий автопереход на Edge (сеть), если Silero/Piper упали
    },
    "brain": {
        "ollama_url": "http://127.0.0.1:11434",
        "model": "qwen3:8b",
        "fast_model": "qwen2.5:3b",   # лёгкая модель для разговора в звонке
        "timeout_s": 120,
        "history_turns": 8,
        "max_steps": 8,
        "think": False,
        "route_tools": True,
        "temperature": 0.3,
        "num_predict": 400,
        "num_ctx": 8192,
    },
    # режим видеосвязи: как часто Юки сам смотрит на экран
    "live": {
        "preview_fps": 8.0,      # частота живого кадра в интерфейсе
        "min_gap_s": 2.0,        # не чаще этого будим модель зрения на смене сцены
        "idle_refresh_s": 30.0,  # если ничего не менялось — освежить описание
        "preview_side": 640,
        "max_side": 512,         # кадр для модели зрения: меньше сторона — быстрее ответ
        "proactive": True,       # сам предлагает помощь, увидев ошибку на экране
        "hint_gap_s": 90.0,      # не чаще одной подсказки за это время
    },
    # интерфейс: панель компаньона на рабочем столе и меню управления
    "ui": {
        "language": "ru",             # язык интерфейса: ru | en
        "accent": "aqua",             # акцент меню: aqua | violet | amber | rose
        "animations": True,           # плавные переходы панелей
        "blur": True,                 # стеклянные подложки
        "autostart": False,           # запуск вместе с Windows (ветка HKCU\...\Run)
    },
    # живой персонаж на рабочем столе
    "companion": {
        "enabled": True,
        "name": "Юки",
        "voice": "mira",              # профиль из core/voices.py
        "character": "lacrimosa",     # модель из ui3d/characters/index.json
        "framing": "full",            # план камеры: full | bust | close
        "quality": "high",            # high | medium | low — нагрузка на видеокарту
        "scale": 1.0,                 # размер фигуры на экране
        "opacity": 1.0,
        "always_on_top": True,
        "click_through": False,       # окно не перехватывает клики
        "subtitles": True,            # показывать реплики под персонажем
        "idle_motion": True,          # дыхание, моргание, микродвижения
        "follow_cursor": True,        # взгляд и наклон головы за курсором
        "lip_sync": True,
        "idle_talk": True,            # сама подаёт голос после долгой тишины
        "idle_talk_minutes": 15,      # сколько молчания считать «давно ничего не было»
        "emotion_style": "warm",      # warm | calm | playful
        "position": None,             # [x, y] последнего положения окна
    },
    "account": {
        "name": "Оператор",
        "handle": "",
        "avatar": "",
    },
    # камера включается вместе со звонком: узнаёт лицо и держит взгляд аватара
    "camera": {
        "enabled": True, "index": 0, "width": 640, "height": 480, "fps": 15.0,
        "gestures": True,   # управление музыкой и громкостью жестами руки
    },
    # панель быстрого запуска: список правится прямо в меню
    "quick_launch": {"apps": None},
    "web": {"default_city": ""},
    "files": {"search_scope": "home", "restrict_paths": False},
    "contacts": {},
    "wake": {"enabled": False, "words": ["юки", "yuki"]},
    "server": {"host": "127.0.0.1", "port": 8765, "open_browser": True},
}

# переменные окружения, которыми удобно править настройки без правки файла
ENV_OVERRIDES: Mapping[str, tuple[str, str, type]] = {
    "JARVIS_MODEL": ("brain", "model", str),
    "JARVIS_OLLAMA_URL": ("brain", "ollama_url", str),
    "JARVIS_TTS_ENGINE": ("tts", "engine", str),
    "JARVIS_VOICE_PRESET": ("tts", "voice_preset", str),
    "JARVIS_STT_MODEL": ("stt", "model_size", str),
    "JARVIS_STT_DEVICE": ("stt", "device", str),
    "JARVIS_CITY": ("web", "default_city", str),
    "JARVIS_SEARCH_SCOPE": ("files", "search_scope", str),
}

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load_env(path: Path | None = None) -> None:
    """Читает .env, не перетирая уже заданные переменные окружения."""
    target = path or ENV_PATH
    if not target.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(target, override=False)
        return
    except ImportError:
        pass
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, _, value = clean.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Рекурсивное слияние словарей без мутации аргументов."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge(current, value)
        else:
            merged[key] = value
    return merged


def _expand(value: Any) -> Any:
    """Подставляет ${ПЕРЕМЕННАЯ} из окружения — так ключи не попадают в репозиторий."""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, Mapping):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value


def _apply_env(cfg: dict[str, Any]) -> dict[str, Any]:
    result = dict(cfg)
    for name, (section, key, kind) in ENV_OVERRIDES.items():
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        block = dict(result.get(section, {}))
        try:
            block[key] = kind(raw)
        except (TypeError, ValueError):
            continue
        result[section] = block
    return result


def load(path: Path | None = None) -> dict[str, Any]:
    """Читает конфиг, накладывает его на значения по умолчанию и применяет окружение."""
    load_env()
    target = path or CONFIG_PATH
    raw: Mapping[str, Any] = {}
    if target.exists():
        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise ValueError(f"Некорректный JSON в {target}: {err}") from err
        if not isinstance(parsed, Mapping):
            raise ValueError(f"Ожидался объект в {target}")
        raw = parsed
    return _apply_env(_expand(_merge(DEFAULTS, raw)))


def save_section(section: str, values: Mapping[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Дописывает значения в раздел config.json, не трогая остальные настройки.

    Пишем только то, что изменилось: файл остаётся читаемым, комментарии пользователя
    в соседних разделах не страдают, а выбор (например голос) переживает перезапуск.
    """
    target = path or CONFIG_PATH
    raw: dict[str, Any] = {}
    if target.exists():
        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(parsed, Mapping):
                raw = dict(parsed)
        except json.JSONDecodeError:
            raw = {}

    block = dict(raw.get(section) or {})
    block.update(values)
    raw[section] = block
    target.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return raw


def resolve_path(value: str | None) -> Path | None:
    """Превращает относительный путь из конфига в абсолютный (относительно корня проекта)."""
    if not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (ROOT / candidate)
