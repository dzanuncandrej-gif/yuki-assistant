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

DEFAULT = "jarvis"


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
    Profile(
        key="jarvis",
        title="ДЖАРВИС",
        character="низкий спокойный мужской",
        model_name="ru_RU-dmitri-medium",
        remote="ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx",
        preset="cinema",
        length_scale=0.9,   # бодрый темп: медленная речь ощущается как «тормозит»
        gain=1.0,
        noise_scale=0.58,   # меньше шума в возбуждении — чище согласные
        noise_w=0.75,       # ровнее длительности фонем, речь не «плавает»
        sample="Юки на связи. Системы в норме, слушаю вас.",
        silero_speaker="aidar",
        edge_voice="ru-RU-DmitryNeural",
        edge_rate="+4%",
        edge_pitch="-12Hz",
        edge_voice_en="en-US-GuyNeural",
    ),
    Profile(
        key="atlas",
        title="АТЛАС",
        character="молодой естественный мужской",
        model_name="ru_RU-ruslan-medium",
        remote="ru/ru_RU/ruslan/medium/ru_RU-ruslan-medium.onnx",
        preset="natural",
        length_scale=0.96,
        gain=1.0,
        noise_scale=0.62,
        noise_w=0.78,
        sample="Атлас на связи. Говорю обычным живым голосом.",
        silero_speaker="eugene",
        edge_voice="ru-RU-DmitryNeural",
        edge_rate="+8%",
        edge_pitch="+6Hz",
        edge_voice_en="en-US-ChristopherNeural",
    ),
    Profile(
        key="aura",
        title="АУРА",
        character="мягкий женский",
        model_name="ru_RU-irina-medium",
        remote="ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        preset="natural",
        length_scale=0.96,
        gain=0.98,
        noise_scale=0.62,
        noise_w=0.78,
        sample="Аура на связи. Мой голос мягче и спокойнее.",
        silero_speaker="baya",
        edge_voice="ru-RU-SvetlanaNeural",
        edge_rate="+6%",
        edge_pitch="+0Hz",
        edge_voice_en="en-US-JennyNeural",
    ),
    Profile(
        key="samurai",
        title="САМУРАЙ",
        character="глубокий властный мужской",
        model_name="ru_RU-dmitri-medium",
        remote="ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium.onnx",
        preset="samurai",
        length_scale=0.94,
        # пик после обработки был 0.45 — половина запаса пропадала впустую,
        # и властный голос звучал тише, чем должен
        gain=1.25,
        noise_scale=0.55,
        noise_w=0.72,
        sample="Я слушаю. Задайте вопрос — отвечу по существу.",
        silero_speaker="aidar",
        edge_voice="ru-RU-DmitryNeural",
        # Тон опускает сам синтез: это чисто и не даёт артефактов, в отличие от
        # пересэмплирования на нашей стороне. Темп чуть выше обычного — быстрая
        # ровная речь звучит уверенно, медленная читается как неповоротливость.
        # Минус тридцать четыре герца звучали неестественно — тон уезжал так низко,
        # что синтез начинал «квакать» на длинных гласных. Восемнадцать дают глубину
        # без искажения. Темп чуть сбавлен: спокойная речь весомее торопливой.
        edge_rate="+4%",
        edge_pitch="-18Hz",
        edge_voice_en="en-US-EricNeural",
    ),
    # --- голоса экранного компаньона: живые, эмоциональные, женские ---
    Profile(
        key="mira",
        title="МИРА",
        character="живой аниме-женский, тёплый",
        model_name="ru_RU-irina-medium",
        remote="ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        preset="anime",
        length_scale=0.92,   # чуть быстрее: живая речь, а не диктор
        gain=1.0,
        noise_scale=0.66,    # больше вариаций интонации — меньше «робота»
        noise_w=0.82,
        sample="Я Мира. Я рядом — просто скажи, и я всё сделаю.",
        silero_speaker="xenia",
        edge_voice="ru-RU-SvetlanaNeural",
        edge_rate="+9%",
        edge_pitch="+22Hz",
        edge_voice_en="en-US-JennyNeural",
    ),
    Profile(
        key="yuki",
        title="ЮКИ",
        character="звонкий аниме-женский, игривый",
        model_name="ru_RU-irina-medium",
        remote="ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        preset="anime",
        length_scale=0.88,
        gain=1.0,
        noise_scale=0.70,
        noise_w=0.85,
        sample="Юки на связи! Давай уже что-нибудь придумаем вместе.",
        silero_speaker="kseniya",
        edge_voice="ru-RU-SvetlanaNeural",
        edge_rate="+14%",
        edge_pitch="+34Hz",
        edge_voice_en="en-US-AnaNeural",
    ),
    Profile(
        key="sora",
        title="СОРА",
        character="спокойный аниме-женский, мягкий",
        model_name="ru_RU-irina-medium",
        remote="ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        preset="anime_soft",
        length_scale=0.96,
        gain=0.98,
        noise_scale=0.62,
        noise_w=0.80,
        sample="Сора здесь. Говорю тихо и спокойно, чтобы тебе было уютно.",
        silero_speaker="baya",
        edge_voice="ru-RU-SvetlanaNeural",
        edge_rate="+2%",
        edge_pitch="+14Hz",
        edge_voice_en="en-US-AriaNeural",
    ),
)

# голоса, которые предлагаются экранному компаньону: женские и живые
COMPANION_KEYS: tuple[str, ...] = ("mira", "yuki", "sora", "aura")

# как голос могут назвать вслух: имя, синоним, английское написание
ALIASES: dict[str, str] = {
    "юки": "jarvis", "jarvis": "jarvis", "юки": "jarvis", "юки": "jarvis",
    "основной": "jarvis", "низкий": "jarvis", "стандартный": "jarvis",
    "атлас": "atlas", "atlas": "atlas", "атласа": "atlas", "атласом": "atlas",
    "молодой": "atlas", "обычный": "atlas",
    "аура": "aura", "aura": "aura", "ауру": "aura", "ауры": "aura", "аурой": "aura",
    "женский": "aura", "женским": "aura", "мягкий": "aura",
    "мира": "mira", "миру": "mira", "миры": "mira", "мирой": "mira", "mira": "mira",
    "компаньон": "mira", "аниме": "mira",
    "юки": "yuki", "юку": "yuki", "yuki": "yuki", "игривый": "yuki", "звонкий": "yuki",
    "сора": "sora", "сору": "sora", "sora": "sora", "тихий": "sora", "спокойный": "sora",
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
