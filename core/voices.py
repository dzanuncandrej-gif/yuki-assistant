"""Каталог голосов Piper: три готовых персонажа и переключение между ними.

Профиль задаёт не только файл модели, но и характер: обработку тембра, темп речи и
громкость. Выбранный голос сохраняется в config.json, поэтому переживает перезапуск.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config

MODELS_DIR = config.ROOT / "models" / "piper"
BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# основной движок: одна модель Silero содержит всех дикторов сразу
SILERO_PATH = config.ROOT / "models" / "silero" / "v4_ru.pt"
SILERO_URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"

DEFAULT = "william"


def silero_ready() -> bool:
    return SILERO_PATH.exists() and SILERO_PATH.stat().st_size > 1_000_000


class VoiceError(RuntimeError):
    """Голос не найден или не скачан."""


@dataclass(frozen=True)
class Profile:
    key: str
    title: str
    character: str          # как звучит — короткой строкой для интерфейса и голоса
    model_name: str         # ru_RU-dmitri-medium
    remote: str             # путь внутри репозитория piper-voices
    preset: str             # пресет обработки из voicefx
    length_scale: float     # темп: меньше — быстрее
    gain: float = 1.0
    noise_scale: float = 0.6
    noise_w: float = 0.85
    sample: str = "Юки на связи. Так звучит мой голос."
    # диктор Silero — основной движок: одна модель на все голоса, переключение мгновенное
    silero_speaker: str = "aidar"
    # запасной нейроголос Edge: используется, когда нет ни Silero, ни Piper.
    edge_voice: str = "ru-RU-DmitryNeural"
    edge_rate: str = "+0%"
    edge_pitch: str = "+0Hz"
    # английский голос той же интонации: Silero и Piper знают только русский,
    # поэтому английский режим ассистента всегда говорит через Edge
    edge_voice_en: str = "en-US-AriaNeural"
    # грамматический род ассистента: «я нашла» или «я нашёл» — см. core/persona.py
    gender: str = "f"

    @property
    def model_path(self) -> Path:
        return MODELS_DIR / f"{self.model_name}.onnx"

    @property
    def config_path(self) -> Path:
        return Path(f"{self.model_path}.json")

    @property
    def model_url(self) -> str:
        return f"{BASE_URL}/{self.remote}"

    @property
    def installed(self) -> bool:
        """Голос доступен: есть модель Silero (одна на всех) либо файл Piper."""
        return silero_ready() or self.piper_installed

    @property
    def piper_installed(self) -> bool:
        return self.model_path.exists() and self.config_path.exists()

    def overrides(self) -> dict[str, Any]:
        """Значения, которые профиль подставляет в настройки синтеза."""
        return {
            "piper_model": str(self.model_path),
            "voice_preset": self.preset,
            "voice_gain": self.gain,
            "piper_length_scale": self.length_scale,
            "piper_noise_scale": self.noise_scale,
            "piper_noise_w": self.noise_w,
            "silero_speaker": self.silero_speaker,
            "edge_voice": self.edge_voice,
            "edge_rate": self.edge_rate,
            "edge_pitch": self.edge_pitch,
        }


PROFILES: tuple[Profile, ...] = (
    # Мужские голоса выбраны на слух 30.09.2026 со страницы прослушки: William,
    # Rémy и Дмитрий. Все три — нейроголоса Microsoft, по Whisper 0–3 % ошибок.
    # Тон синтезу не сдвигаем и звук не обрабатываем: нейроголос уже сведён, а
    # компрессия и эквалайзер поверх делали его менее естественным.
    # Без сети говорит Silero того же пола.
    Profile(
        key="william",
        gender="m",
        title="WILLIAM",
        character="мужской: бодрый, дружелюбный, живой",
        model_name="ru_RU-dmitri-medium",
        remote="ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx",
        preset="raw",
        length_scale=0.94,
        sample="Уильям на связи. Говори, что делаем.",
        silero_speaker="eugene",
        edge_voice="en-AU-WilliamMultilingualNeural",
        edge_rate="+0%",
        edge_pitch="+0Hz",
        edge_voice_en="en-AU-WilliamMultilingualNeural",
    ),
    Profile(
        key="remy",
        gender="m",
        title="RÉMY",
        character="мужской: мягкий, спокойный, бархатный",
        model_name="ru_RU-dmitri-medium",
        remote="ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx",
        preset="raw",
        length_scale=0.94,
        sample="Реми здесь. Спокойно, всё сделаю.",
        silero_speaker="eugene",
        edge_voice="fr-FR-RemyMultilingualNeural",
        edge_rate="+0%",
        edge_pitch="+0Hz",
        edge_voice_en="fr-FR-RemyMultilingualNeural",
    ),
    Profile(
        key="dmitry",
        gender="m",
        title="ДМИТРИЙ",
        character="мужской: родной русский диктор, чёткий",
        model_name="ru_RU-dmitri-medium",
        remote="ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx",
        preset="raw",
        length_scale=0.94,
        sample="Дмитрий на связи. Все системы в норме.",
        silero_speaker="aidar",
        edge_voice="ru-RU-DmitryNeural",
        edge_rate="+0%",
        edge_pitch="+0Hz",
        edge_voice_en="en-US-AndrewMultilingualNeural",
    ),
    # Женский голос выбран на слух со страницы прослушки: Vivienne в варианте
    # «живее» — темп +6 %, тон +4 Гц. Остальные женские кандидатки не понравились.
    Profile(
        key="yuki",
        title="ЮКИ",
        character="женский: живой, тёплый, выразительный",
        model_name="ru_RU-irina-medium",
        remote="ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        preset="raw",
        length_scale=0.94,
        noise_scale=0.64,
        noise_w=0.8,
        sample="Юки на связи! Я рядом — скажи, и я всё сделаю.",
        silero_speaker="xenia",
        edge_voice="fr-FR-VivienneMultilingualNeural",
        edge_rate="+6%",
        edge_pitch="+4Hz",
        edge_voice_en="fr-FR-VivienneMultilingualNeural",
    ),
)

# голоса, которые предлагаются экранному компаньону
COMPANION_KEYS: tuple[str, ...] = ("yuki", "william", "remy", "dmitry")

# Прежние голоса ведут в новые: в config.json и в командах они ещё встречаются.
LEGACY: dict[str, str] = {
    "jarvis": "william", "atlas": "william", "samurai": "dmitry",
    "aura": "yuki", "mira": "yuki", "sora": "yuki",
}

# как голос могут назвать вслух: имя, синоним, английское написание
ALIASES: dict[str, str] = {
    "william": "william", "уильям": "william", "уильяма": "william", "вильям": "william",
    "вильяма": "william", "уильямом": "william", "мужской": "william", "мужским": "william",
    "основной": "william", "джарвис": "william", "джарвиса": "william", "атлас": "william",
    "remy": "remy", "rémy": "remy", "реми": "remy", "рэми": "remy", "реми́": "remy",
    "мягкий": "remy", "бархатный": "remy",
    "dmitry": "dmitry", "дмитрий": "dmitry", "дмитрия": "dmitry", "дмитрием": "dmitry",
    "дима": "dmitry", "диму": "dmitry", "диктор": "dmitry", "русский": "dmitry", "самурай": "dmitry",
    "юки": "yuki", "юку": "yuki", "yuki": "yuki", "женский": "yuki", "женским": "yuki",
    "девушка": "yuki", "аура": "yuki", "ауру": "yuki", "мира": "yuki", "сора": "yuki",
}


# ---------------------------------------------------------------- связь с работающим ассистентом
#
# Команды и инструменты не знают об объекте ассистента. Он сам оставляет здесь три
# функции, и переключение голоса из любой точки программы попадает в живой синтез.

_runtime: dict[str, Any] = {"apply": None, "current": None, "preview": None}


def bind(apply: Any, current: Any, preview: Any) -> None:
    _runtime.update({"apply": apply, "current": current, "preview": preview})


def bound() -> bool:
    return _runtime["apply"] is not None


def apply(profile: Profile) -> Profile:
    """Переключает голос в работающем ассистенте и запоминает выбор."""
    if not profile.installed:
        raise VoiceError(
            f"голос {profile.title} не скачан. Выполни: "
            f"python scripts/download_piper_voice.py --profile {profile.key}"
        )
    switch = _runtime["apply"]
    if switch is None:
        raise VoiceError("синтез речи ещё не запущен")
    switch(profile)
    remember(profile)
    return profile


def active() -> Profile:
    """Голос, которым ассистент говорит прямо сейчас."""
    reader = _runtime["current"]
    if reader is not None:
        profile = get(reader())
        if profile is not None:
            return profile
    return current(config.load().get("tts", {}))


def preview(profile: Profile) -> str:
    """Даёт послушать голос, не меняя выбранный."""
    if not profile.installed:
        raise VoiceError(f"голос {profile.title} не скачан")
    player = _runtime["preview"]
    if player is None:
        raise VoiceError("синтез речи ещё не запущен")
    player(profile)
    return profile.sample


def catalog() -> tuple[Profile, ...]:
    return PROFILES


def get(key: str | None) -> Profile | None:
    needle = str(key or "").strip().lower()
    needle = LEGACY.get(needle, needle)
    for profile in PROFILES:
        if profile.key == needle:
            return profile
    return None


def resolve(spoken: str) -> Profile:
    """«переключись на атлас» → профиль ATLAS. Понимает падежи и латиницу."""
    needle = str(spoken or "").strip().lower().strip(".,!?«»\"'")
    if not needle:
        raise VoiceError("не понял, какой голос включить")

    direct = get(needle) or get(ALIASES.get(needle, ""))
    if direct is not None:
        return direct

    for word in needle.replace("-", " ").split():
        found = get(word) or get(ALIASES.get(word, ""))
        if found is not None:
            return found

    for alias, key in ALIASES.items():
        if alias in needle:
            profile = get(key)
            if profile is not None:
                return profile

    raise VoiceError(f"голоса «{spoken}» нет. Доступны: {', '.join(p.title for p in PROFILES)}")


def default_profile() -> Profile:
    """Первый установленный голос: сначала выбранный по умолчанию, потом любой скачанный."""
    preferred = get(DEFAULT)
    if preferred is not None and preferred.installed:
        return preferred
    for profile in PROFILES:
        if profile.installed:
            return profile
    return preferred or PROFILES[0]


def current(cfg: dict[str, Any] | None = None) -> Profile:
    """Голос из настроек. Если он не скачан — берём любой доступный."""
    key = str((cfg or {}).get("voice") or DEFAULT)
    profile = get(key) or get(DEFAULT)
    if profile is None:
        return PROFILES[0]
    return profile if profile.installed else default_profile()


def remember(profile: Profile) -> None:
    """Сохраняет выбор в config.json, чтобы он пережил перезапуск."""
    config.save_section("tts", {"voice": profile.key})


def describe(profile: Profile) -> str:
    mark = "" if profile.installed else " — не скачан"
    return f"{profile.title} ({profile.character}){mark}"


def summary() -> str:
    return "; ".join(describe(profile) for profile in PROFILES)


def missing() -> tuple[Profile, ...]:
    return tuple(profile for profile in PROFILES if not profile.installed)
