"""Оркестратор: микрофон → распознавание → команда или агент → действие → речь.

Порядок важен. Сначала пробуем быстрые точные команды (они выполняются за миллисекунды),
и только если фраза на них не похожа — идём в агента с инструментами. Ответ произносится
потоково и обрывается по слову «стоп» или по громкому перебиванию.
"""

from __future__ import annotations

import contextlib
import random
import re
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import agent as agent_module
from . import (
    audio,
    bus,
    camera,
    commands,
    language,
    lexicon,
    live,
    messengers,
    mood,
    questions,
    reminders,
    stt,
    tools,
    tts,
    voices,
    web,
)
from . import text as text_utils

_ECHO_TAIL_S = 0.35  # столько после своей реплики микрофон ещё игнорируется (хвост эха)
_BARGE_IN_GRACE_S = 1.2  # столько от начала реплики перебить нельзя — защита от эха

# фразы, которым нужны инструменты: их нельзя отдавать лёгкой разговорной модели
_NEEDS_TOOLS = re.compile(
    r"\b(?:открой|запусти|включи|выключи|закрой|сверни|разверни|поставь|создай|удали|скопируй|"
    r"перемести|переименуй|напиши|напечатай|отправь|нажми|кликни|найди|поищи|погугли|скачай|"
    r"перейди|прочитай|запомни|забудь|напомни|отмени|громкост\w+|яркост\w+|скриншот|погод\w+|"
    r"новост\w+|курс|время|который\s+час|какое\s+сегодня|сколько\s+(?:времени|места|памяти)|"
    r"что\s+(?:запущено|открыто)|камер\w+|лицо|музык\w+|трек|"
    r"что\s+(?:сейчас\s+)?на\s+экране|на\s+экране|видишь\s+на\s+экран\w*|"
    r"какие\s+окна|сколько\s+заряд\w*)\b",
    re.IGNORECASE,
)

# «стоп», «хватит», «замолчи» — обрывают речь и ничего больше не делают
STOP_WORDS = re.compile(
    r"^(?:юки[\s,]*)?(?:стоп|хватит|замолчи|молчи|тише|тихо|отставить|заткнись|stop|shut up|quiet|enough)"
    r"[\s.!]*$",
    re.IGNORECASE,
)

# после ответа ассистента столько секунд можно говорить без обращения по имени
FOLLOW_UP_S = 20.0

# Видеосвязь голосом. «Позвони маме» сюда не попадает намеренно: звонить людям
# Юки не умеет, а открывать вместо этого свой звонок было бы враньём.
CALL_START = re.compile(
    r"(видео\s*связ|видео\s*звон|созвон|позвони\s+мне|давай\s+(?:по)?звон|"
    r"(?:включи|начни|открой)\s+(?:видео)?звонок|video\s*call|call\s+me)",
    re.IGNORECASE,
)
CALL_END = re.compile(
    r"((?:заверши|закончи|положи|отключи|сбрось|выключи|прекрати)\s+(?:видео)?(?:звонок|связь|видеосвязь|трубку)|"
    r"^\s*отбой(?![а-яё])|end\s+(?:the\s+)?call|hang\s+up)",
    re.IGNORECASE,
)

# рассказ о себе: такие реплики стоит разобрать и запомнить надолго
PERSONAL = re.compile(
    r"(?:\bменя\s+зовут\b|\bя\s+(?:работаю|учусь|живу|люблю|ненавижу|занимаюсь|играю|"
    r"увлекаюсь|родился|родилась|programm\w*)\b|\bмо(?:й|я|ё|и)\s+\w+|\bу\s+меня\s+\w+|"
    r"\bмне\s+\d+\b|\bя\s+из\s+\w+|\bпредпочитаю\b|\bобычно\s+я\b|\bкаждый\s+день\s+я\b)",
    re.IGNORECASE,
)

# чаще этого разбор реплик на факты не запускаем: видеокарта нужна разговору
_LEARN_GAP_S = 25.0

# как часто языковую модель возвращают в память после разбора экрана
_REWARM_GAP_S = 20.0

# как часто субтитры обновляются во время речи: чаще — мельтешение, реже — рывки
_CAPTION_GAP_S = 0.35

# если ответа нет дольше этого, вставляем короткую живую реплику — иначе тишина
# читается как «не услышала»
_FILLER_AFTER_S = 1.9
# Заготовки нарочно нейтральные. «Сейчас посмотрю» перед ответом на «меня зовут
# Андрей» звучит нелепо: в этот момент никто ничего не ищет.
_FILLERS: tuple[str, ...] = ("Секунду.", "Минутку.", "Так, сейчас.", "Ага, момент.")

# пауза перед разбором реплики на факты: сначала человек должен успеть заговорить
_LEARN_DELAY_S = 2.5

# дольше этого ответ не ждём: зависший инструмент не должен оставлять её немой
_ANSWER_LIMIT_S = 180.0

# «а ты умеешь…», «ну и как ты?», «слушай, тебе нравится…» — разговорные зачины
# с частицами. Без них фраза уходила в тяжёлый путь и отвечала тринадцать секунд.
_LEAD = r"(?:(?:а|и|ну|ой|эй|слушай|скажи|слушай-ка|кстати)[\s,]+){0,2}"
_ABOUT_HER = rf"^{_LEAD}(?:юки[\s,!]*)?{_LEAD}(?:ты|тебе|тебя|твой|твоя|твоё|твои)"

# Явные признаки разговора, а не приказа: приветствия, вопросы о самочувствии,
# благодарности, короткие реплики. Проверяются только когда глагол действия в
# фразе не встретился — «включи музыку» приказ, даже если начинается с «слушай».
_SMALL_TALK = re.compile(
    rf"^{_LEAD}(?:юки[\s,!]*)?(?:"
    r"привет\w*|здравствуй\w*|хай|доброе\s+утро|добрый\s+(?:день|вечер)|"
    r"как\s+(?:ты|дела|жизнь|настроение|сама)|что\s+(?:делаешь|нового|как)|"
    r"ты\s+(?:тут|здесь|тут\?|живая|умная|classная)|"
    r"спасибо\w*|благодарю|пожалуйста|извини\w*|прости\w*|"
    r"пока|до\s+свидания|спокойной\s+ночи|доброй\s+ночи|"
    r"ты\s+кто|кто\s+ты|как\s+тебя\s+зовут|расскажи\s+о\s+себе|"
    r"ага|угу|ясно|понятно|ладно|хорошо|окей|ок|да|нет|"
    r"скучно|устал\w*|грустно|весело|люблю\s+тебя|молодец|умница"
    r")\b",
    re.IGNORECASE,
)


# «а ты умеешь…», «ну и как ты?», «слушай, тебе нравится…» — разговорные зачины
# с частицами. Без них фраза уходила в тяжёлый путь и отвечала тринадцать секунд.
_LEAD = r"(?:(?:а|и|ну|ой|эй|слушай|скажи|слушай-ка|кстати)[\s,]+){0,2}"
_ABOUT_HER = rf"^{_LEAD}(?:юки[\s,!]*)?{_LEAD}(?:ты|тебе|тебя|твой|твоя|твоё|твои)\b"

# только глаголы действия, без предметов: ими проверяется приказ там, где
# существительное («музыка», «погода») ещё ничего не значит
_ACTION_VERBS = re.compile(
    r"\b(?:открой|открыть|запусти|запустить|включи|включить|выключи|закрой|закрыть|сверни|"
    r"разверни|поставь|сделай|создай|удали|скопируй|перемести|переименуй|напиши|напечатай|"
    r"набери|введи|отправь|передай|нажми|кликни|прокрути|найди|поищи|погугли|покажи|скачай|"
    r"перейди|прочитай|проверь|посмотри|запомни|забудь|напомни|останови|послушаем|включим)\b",
    re.IGNORECASE,
)


# Модель охотно дописывает к списку фактов пояснение вроде «других фактов нет».
# Без отсева оно попадало в долгую память наравне с настоящими фактами.
_NOT_A_FACT = re.compile(
    r"^(?:нет\b|других?\s|больше\s+фактов|фактов\s+(?:нет|не)|в\s+(?:данной|этой)\s+реплике|"
    r"информаци\w+\s+о|ничего\s+(?:не|больше))",
    re.IGNORECASE,
)


def _facts_from(raw: str, limit: int = 4) -> tuple[str, ...]:
    """Строки-факты из ответа модели, без пояснений и повторов."""
    found: list[str] = []
    for line in (raw or "").splitlines():
        fact = line.strip(" -•*\t").strip()
        if len(fact) < 6 or len(fact) > 140 or _NOT_A_FACT.match(fact):
            continue
        if fact not in found:
            found.append(fact)
        if len(found) >= limit:
            break
    return tuple(found)


def _is_small_talk(text: str) -> bool:
    """Обращаются к ней или просят что-то сделать.

    Порядок проверок важен. Сначала глаголы действия: если человек просит
    открыть, включить или найти — это приказ при любом обрамлении. И только
    потом разговорные обороты. Длинная фраза без глагола действия тоже считается
    разговором: приказы люди формулируют коротко.
    """
    clean = text.strip()
    if not clean:
        return False

    # Приказ узнаётся по глаголу действия — при любом обрамлении.
    if _ACTION_VERBS.search(clean):
        return False
    # Предметы, за которыми нужно лезть в систему или в сеть: погода, громкость,
    # новости, окна. Про них отвечает только инструмент.
    if _NEEDS_TOOLS.search(clean):
        return False

    # Всё остальное — разговор.
    #
    # Раньше здесь требовалось совпадение со списком разговорных зачинов, и любая
    # фраза мимо списка уезжала в путь с инструментами. «Как твои дела» в список
    # не попадала: там было «как дела», но не «как твои дела». Модель получала
    # полсотни функций на невинный вопрос и открывала телеграм.
    #
    # Признавать разговором всё, где нет ни глагола действия, ни системного
    # предмета, безопасно с обеих сторон: разговорный путь физически лишён
    # инструментов и ничего запустить не может, а команда без глагола действия
    # почти не встречается.
    return True

# так начинается обращение к ассистенту: приказ или вопрос. Всё остальное в режиме
# звонка считается посторонней речью — из колонок и из комнаты её приходит много.
DIRECTED = re.compile(
    r"^\s*(?:открой|открыть|запусти|включи|выключи|закрой|заверши|сверни|разверни|переключись|"
    r"поставь|сделай|создай|удали|скопируй|перемести|переименуй|напиши|напечатай|набери|введи|"
    r"отправь|передай|нажми|кликни|прокрути|найди|поищи|погугли|покажи|прочитай|проверь|посмотри|"
    r"расскажи|объясни|переведи|повтори|напомни|запомни|забудь|скажи|давай|помоги|останови|стоп|"
    r"хватит|замолчи|отмена|продолжи|"
    r"что|чем|кто|где|когда|почему|зачем|как|какой|какая|какие|каком|сколько|который|которое|"
    r"во\s+сколько|можешь|умеешь|умеешь\s+ли|есть\s+ли|правда\s+ли|а\s+что|а\s+как|а\s+сколько|"
    r"юки|атлас|аура|"
    r"open|close|start|stop|show|find|tell|what|how|why|who|where|when|can\s+you)\b",
    re.IGNORECASE,
)



_MD_MARKS = re.compile(r"[*_`#>|]+")


def _gist_cut(text: str, final: bool = False) -> int | None:
    """Где кончается суть: пустая строка, строка разметки или второе предложение."""
    body = text.lstrip()
    offset = len(text) - len(body)
    for marker in ("\n\n", "\n#", "\n-", "\n*", "\n1.", "\n```", "\n|"):
        index = body.find(marker)
        if index > 0:
            return offset + index
    if len(body) > 260 or final:
        ends = [m.end() for m in re.finditer(r"[.!?…](?=\s)", body)]
        if len(ends) >= 2:
            return offset + ends[1]
        if ends:
            return offset + ends[0]
        return offset + min(len(body), 260) if len(body) > 260 else None
    return None


def _speakable(text: str) -> str:
    """Суть без markdown и без служебного «Суть:» — её читает синтез."""
    clean = _MD_MARKS.sub("", text).strip()
    clean = re.sub(r"^(?:суть|коротко|кратко)\s*[:—-]\s*", "", clean, flags=re.IGNORECASE)
    return clean


class Assistant:
    """Рабочий поток голосового цикла."""

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self._cfg = dict(cfg)
        self._stop = threading.Event()
        # поднят ли синтез речи. Приветствие ждёт этого события: сказанное до
        # загрузки модели просто теряется
        self.voice_ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._muted = threading.Event()
        self._speech_lock = threading.Lock()
        self._speech_stop = threading.Event()
        self._speech_guard = threading.Lock()
        self._speech_epoch = 0
        self._speech_started = 0.0
        self._last_answer = ""
        self._deaf_until = 0.0
        self._open_until = 0.0  # до этого момента можно говорить без «Юки»
        self._watcher: live.Watcher | None = None  # включён только в режиме звонка
        self._call_log: live.CallLog | None = None
        self._last_hint = 0.0
        self._last_learn = 0.0
        self._last_rewarm = 0.0
        self._mood_sent = False
        self._barged = False
        self._last_caption = 0.0
        self._catcher = None   # кто ждёт следующую реплику вместо агента
        self._catch_lock = threading.Lock()
        self._turn = 0  # номер реплики: по нему фоновые задачи понимают, что разговор ушёл дальше
        self._camera: camera.Camera | None = None

        self._transcriber = stt.Transcriber(cfg["stt"])
        # имя владельца агент подмешивает в контекст: обращение по имени — половина
        # ощущения, что рядом живой собеседник, а не безличный интерфейс
        brain = {**cfg["brain"], "owner": str(cfg.get("account", {}).get("name", "")).strip()}
        self._agent = agent_module.Agent(brain)
        from .coding import Coder

        self._talking = 0
        self._talk_lock = threading.Condition()
        self._quiet_since = time.monotonic()
        self.coder = Coder(
            lambda system, user, limit, think: self._agent.generate(system, user, limit, think),
            lambda system, user, limit, think: self._agent.generate_json(system, user, limit, think),
            busy_talking=lambda: self._talking > 0,
            wait_quiet=self._wait_quiet,
        )
        self._voice: tts.Voice | None = None
        self._mic = audio.Microphone(cfg["audio"], on_level=self._on_input_level)
        self._output_device = cfg["audio"].get("output_device")

        web.configure(cfg.get("web"))
        messengers.configure(cfg.get("contacts"))
        self._teach_lexicon()
        reminders.configure(self.say)
        tools.configure(
            {
                "ollama_url": cfg["brain"].get("ollama_url", "http://127.0.0.1:11434"),
                "search_scope": cfg.get("files", {}).get("search_scope", "home"),
                "restrict_paths": cfg.get("files", {}).get("restrict_paths", False),
            }
        )
        commands.configure(
            {
                "ollama_url": cfg["brain"].get("ollama_url", "http://127.0.0.1:11434"),
                "search_scope": cfg.get("files", {}).get("search_scope", "home"),
            }
        )

    def _teach_lexicon(self) -> None:
        """Словарь исправления слов: имена голосов, контакты, установленные программы."""
        lexicon.teach(text_utils.ALL_WAKE_WORDS)
        lexicon.teach(profile.title.lower() for profile in voices.catalog())
        lexicon.teach(self._cfg.get("contacts", {}).keys())
        lexicon.teach(self._cfg.get("contacts", {}).values())
        try:
            from . import apps

            lexicon.teach(apps.ALIASES.keys())
            lexicon.teach(apps.BUILTIN.keys())
            # названия ярлыков из «Пуска»: «фотошоп», «дискорд», «стим» и прочее
            lexicon.teach(name for name in apps.shortcut_index() if len(name) < 24)
        except Exception:
            pass

    # ---------------------------------------------------------------- жизненный цикл

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="jarvis-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.interrupt()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None

    def set_muted(self, muted: bool) -> None:
        self._muted.set() if muted else self._muted.clear()
        bus.bus.log("system", "Микрофон выключен." if muted else "Микрофон включён.")

    def _can_listen(self) -> bool:
        """Пока ассистент говорит (и короткий хвост после), микрофон не слушает."""
        if self._muted.is_set() or self._speech_lock.locked():
            return False
        return time.monotonic() >= self._deaf_until

    # ---------------------------------------------------------------- UI-хуки

    def _on_input_level(self, level: float) -> None:
        if bus.bus.state == bus.LISTENING:
            bus.bus.set_level(level)

    def _on_output_level(self, level: float) -> None:
        if bus.bus.state == bus.SPEAKING:
            bus.bus.set_level(level)

    def _on_viseme(self, shape: dict[str, float]) -> None:
        """Положение рта по звучащему блоку — губы персонажа идут за голосом."""
        bus.bus.publish({"type": "viseme", **shape})

    def _on_step(self, kind: str, text: str) -> None:
        """Показывает в журнале, какие инструменты агент вызывает и что они ответили."""
        if kind == "tool":
            bus.bus.log("system", f"→ {text}")
        elif kind == "tool_result":
            bus.bus.log("system", f"✓ {text[:300]}")
        elif kind == "error":
            bus.bus.log("error", text[:300])
        elif kind == "thought" and text:
            bus.bus.log("system", text[:200])

    # ---------------------------------------------------------------- основной цикл

    def _run(self) -> None:
        try:
            self._boot()
            for utterance in self._mic.utterances(
                self._stop.is_set, gate=self._can_listen, on_barge_in=self._on_barge_in
            ):
                if self._stop.is_set():
                    break
                self._handle_utterance(utterance)
                self._mic.drain()
                bus.bus.set_state(bus.LISTENING)
        except Exception as err:
            bus.bus.log("error", f"Цикл остановлен: {err}")
            bus.bus.set_state(bus.IDLE)

    def _boot(self) -> None:
        bus.bus.set_state(bus.THINKING)
        if self._mic.device_note:
            bus.bus.log("system", f"Микрофон: {self._mic.device_note}, {self._mic.detector_name}.")
        bus.bus.log("system", "Гружу модели…")

        # распознавание и синтез грузятся параллельно: это независимые модели,
        # а последовательная загрузка отнимала лишние секунды при каждом запуске
        speech = threading.Thread(target=self._transcriber.warmup, name="jarvis-stt-warmup", daemon=True)
        speech.start()

        # индекс приложений собирается заранее: первая команда «открой…» иначе
        # ждёт обхода меню «Пуск» и вызова PowerShell — несколько секунд на пустом месте
        from . import apps

        threading.Thread(target=apps.warm_index, name="jarvis-apps-warmup", daemon=True).start()

        try:
            self._voice = tts.Voice(self._cfg["tts"], device=self._output_device)
            # Профиль ставим явно. Внутренние умолчания синтеза приводили к
            # мужскому «Джарвису», даже когда в настройках выбран женский голос:
            # звучал он до первой ручной смены голоса и возвращался после
            # каждого перезапуска.
            self._apply_configured_voice()
            self._voice.warmup()  # голос грузится заранее, иначе первая фраза ждёт модель
            self.voice_ready.set()
            voices.bind(self._quiet_swap, lambda: self.voice_key, self._preview_profile)
            language.bind(self._transcriber, self._voice.speaker)
            language.set_active_quiet(str(self._cfg.get("stt", {}).get("language", "ru")))
            profile = self._voice.profile
            bus.bus.log(
                "system",
                f"Синтез речи: {self._voice.engine_name}"
                + (f", голос {profile.title} ({profile.character})." if profile else "."),
            )
            # остальные голоса подтягиваются в память фоном: переключение станет мгновенным
            threading.Thread(target=self._voice.preload, name="jarvis-voices", daemon=True).start()
            # ходовые короткие реплики заготавливаем заранее — они зазвучат без паузы
            threading.Thread(target=self._voice.prime_cache, name="jarvis-tts-cache",
                             daemon=True).start()
            absent = voices.missing()
            if absent:
                bus.bus.log(
                    "system",
                    "Не скачаны голоса: "
                    + ", ".join(item.title for item in absent)
                    + ". Команда: python scripts/download_piper_voice.py --all",
                )
        except tts.SynthesisError as err:
            bus.bus.log("error", str(err))

        speech.join(timeout=90)
        bus.bus.log(
            "system",
            f"Распознавание: whisper {self._transcriber.model_name} на {self._transcriber.device}.",
        )

        online = self._agent.available(refresh=True)
        bus.bus.log(
            "system",
            f"Агент: {self._agent.model}, инструментов {len(tools.names())}."
            if online
            else "Ollama недоступна — работают только прямые команды.",
        )
        if online:
            threading.Thread(target=self._warm_agent, name="jarvis-llm-warmup", daemon=True).start()
            threading.Thread(target=self._warm_eyes, name="jarvis-ocr-warmup", daemon=True).start()

        tools.study_tools.configure(self._agent, str(self._cfg["brain"].get("ollama_url", "")))

        wake = "по имени «Юки»" if self._cfg["wake"].get("enabled") else "без обращения"
        bus.bus.log("system", f"Готов. Слушаю {wake}.")
        bus.bus.set_state(bus.LISTENING)
        self.say("Юки на связи.")
        bus.bus.set_state(bus.LISTENING)

    def _warm_eyes(self) -> None:
        """Распознавание текста экрана поднимается заранее — первый вопрос про экран без паузы."""
        from . import ocr

        if ocr.warmup():
            bus.bus.log("system", "Зрение: распознавание текста экрана готово.")

    def _check_gpu(self) -> None:
        """Ollama на процессоре отвечает минутами — замечаем и чиним сами."""
        from . import ollama_guard

        url = str(self._cfg["brain"].get("ollama_url", "http://127.0.0.1:11434"))
        verdict = ollama_guard.check(url)
        if verdict == "cpu":
            bus.bus.log("error", "Ollama считает на процессоре, а не на видеокарте — перезапускаю её.")
            if ollama_guard.restart(url):
                self._agent.available(refresh=True)
                self._agent.warmup()
                bus.bus.log("system", "Ollama перезапущена: модель снова на видеокарте.")
            else:
                bus.bus.log("error", "Не смогла перезапустить Ollama — перезапусти её вручную из трея.")

    def _warm_agent(self) -> None:
        result = self._agent.warmup()
        if result and result.startswith("прогрев"):
            bus.bus.log("error", f"LLM: {result}")
        elif result:
            bus.bus.log("system", f"LLM: {result} в памяти.")
            self._check_gpu()

    def _rewarm_agent(self) -> None:
        """Возвращает языковую модель в память видеокарты, не мешая разговору.

        Молча и в фоне: если человек как раз говорит или ждёт ответа, прогрев
        только отнял бы у него видеокарту.
        """
        if self._speech_lock.locked() or bus.bus.state == bus.THINKING:
            return
        now = time.monotonic()
        if now - self._last_rewarm < _REWARM_GAP_S:
            return
        self._last_rewarm = now
        threading.Thread(target=self._agent.warmup, name="jarvis-rewarm", daemon=True).start()

    def _on_barge_in(self) -> None:
        """Громкая речь во время монолога — человек перебивает, замолкаем.

        Перебить можно только то, что уже звучит. Пока ответ ещё считается,
        `_speech_started` держится в бесконечности: иначе случайный шум обрывал
        готовящуюся реплику, а сама фраза человека в это время отбрасывалась
        затвором микрофона — и ответа не было вовсе, без всякой причины.

        Первые секунды речи тоже защищены: собственное эхо обрывало ответ сразу
        после первого слова, и казалось, что он «просто пишет».
        """
        if not self._speech_lock.locked():
            return
        if time.monotonic() - self._speech_started < _BARGE_IN_GRACE_S:
            return
        bus.bus.log("system", "перебили — замолкаю")
        self._barged = True
        self.interrupt()

    # ---------------------------------------------------------------- разбор реплики

    def _handle_utterance(self, utterance) -> None:
        bus.bus.set_state(bus.THINKING)
        started = time.monotonic()
        text, _ = self._transcriber.transcribe(utterance)

        if not text or len(text.strip()) < 2:
            bus.bus.set_state(bus.LISTENING)
            return

        if STOP_WORDS.match(text.strip()):
            self.interrupt()
            bus.bus.log("user", text)
            bus.bus.set_state(bus.LISTENING)
            return

        payload = self._apply_wake_word(text)
        if payload is None:
            # молча проглоченная реплика выглядит как сломанный ассистент: он
            # услышал, но не ответил и ничего не показал. Пусть будет видно, что
            # фраза отброшена именно из-за обращения по имени
            bus.bus.log("system", f"мимо (нужно обращение по имени): {text[:70]}")
            bus.bus.set_state(bus.LISTENING)
            return

        # Реплику мог ждать кто-то другой: диктовка сообщения, ответ на вопрос.
        # Такая фраза — это текст, а не команда, и в агента она не идёт: «передай,
        # что я опоздаю» иначе было бы понято как приказ и что-нибудь запустило.
        catcher = self._take_catcher()
        if catcher is not None:
            bus.bus.log("user", text)
            try:
                catcher(text)
            except Exception as err:
                bus.bus.log("error", f"диктовка: {err}")
            bus.bus.set_state(bus.LISTENING)
            return

        bus.bus.log("user", text)
        self._turn += 1
        # Отмену снимаем ровно один раз за ход. Делать это в say_stream было
        # нельзя: напоминание или приветствие, прозвучавшее сразу после «стоп»,
        # снимало флаг и воскрешало уже отменённый цикл агента.
        self._speech_stop.clear()
        if self._call_log is not None:
            self._call_log.say("Человек", text)
        turn = self._turn
        with self._conversation():
            answer = self.say_stream(self._with_filler(self._respond_stream(payload, turn), turn))
        bus.bus.log("assistant", answer)
        if self._call_log is not None:
            self._call_log.say("Юки", answer)
        bus.bus.log("system", f"обработано за {time.monotonic() - started:.1f} с")
        self._open_until = time.monotonic() + FOLLOW_UP_S
        self._learn(payload, answer)

    def _apply_wake_word(self, text: str) -> str | None:
        """Обращение обязательно, если включено — но не сразу после ответа ассистента.

        Позвать можно именем любого из голосов: «Юки», «Атлас», «Аура». Если
        назвали имя другого персонажа, ассистент заодно переключается на него —
        так у каждого голоса своё обращение.
        """
        wake = self._cfg["wake"]
        stripped = text_utils.strip_wake(text)
        called = text_utils.wake_name(text)

        if self._watcher is not None:
            # во время звонка обращение по имени не нужно, но и реагировать на всё
            # подряд нельзя: из колонок идут чужие голоса, видео и музыка
            if not self._directed(text, called is not None):
                bus.bus.log("system", f"мимо (не мне): {text[:70]}")
                return None
            return text_utils.normalize(stripped if called else text) or text

        # Обращение по имени голос не меняет. Раньше меняло — и это ломало
        # главное: «Юки» распознаётся как обращение с ключом jarvis, профиля с
        # таким именем среди женских нет, подставлялся запасной — низкий мужской
        # ДЖАРВИС. Достаточно было позвать её по имени, чтобы голос перестал быть
        # её собственным. Смена голоса осталась явной командой: «переключись на ауру».

        if not wake.get("enabled"):
            return text_utils.normalize(stripped) or stripped or text
        if called is not None:
            return text_utils.normalize(stripped) or stripped or text
        if time.monotonic() < self._open_until:
            return text_utils.normalize(text) or text

        # услышали речь, но без обращения — показываем это в журнале, чтобы не казалось,
        # будто ассистент «молчит без причины»
        bus.bus.log("system", f"мимо (нет обращения): {text[:80]}")
        return None

    # ---------------------------------------------------------------- режим звонка

    @property
    def live(self) -> bool:
        return self._watcher is not None

    def _suggest_reply(self):
        """Читает переписку, предлагает три ответа: лучший — голосом, все — карточкой."""
        from . import replies

        bus.bus.log("system", "читаю переписку…")
        window = replies.target_window()
        chat, image = replies.read_chat(window)
        try:
            who, asked, options = replies.parse_options(self._agent.reply_options(chat, image))
        except Exception as err:
            bus.bus.log("error", f"варианты ответа: {err}")
            yield "Не разобрала переписку. Открой чат так, чтобы последнее сообщение было видно, и спроси ещё раз."
            return
        suggestion = replies.remember(options, who, asked, window)
        bus.bus.publish({"type": "message", "kind": "report", "text": replies.as_report(suggestion)})
        about = f"{who} спрашивает: {asked}. " if who and asked else (f"Вопрос: {asked}. " if asked else "")
        yield f"{about}Можно ответить так: «{suggestion.current}». Сказать «вставь» — вставлю, «отправь» — отправлю."

    def _retell(self, question: str, prompt: str, note: str, collect, budget: int):
        """Собирает данные и пересказывает их голосом; данные — ещё и карточкой в «Диалог»."""
        bus.bus.log("system", note)
        facts = collect()
        card = "## Сводка\n" + facts.replace("\n", "\n\n")
        bus.bus.publish({"type": "message", "kind": "report", "text": card})
        said = False
        for piece in self._agent.retell_stream(prompt, question, facts, budget):
            said = True
            yield piece
        if not said:
            yield "Сводку собрала, но рассказать не получилось — она в «Диалоге»."

    def _about_playing(self, question: str, kind: str):
        """Что играет — из медиасессии Windows; об исполнителе или песне — из интернета."""
        from . import media

        info = media.playing_info()
        if not info:
            yield "Сейчас ничего не играет. Включи музыку — и я расскажу об исполнителе."
            return
        artist, song = info.get("artist", ""), info.get("song", "")
        if kind == "what":
            yield f"Играет «{song}»" + (f" — {artist}." if artist else ".")
            return
        if kind == "song" and song:
            query = f"{artist} {song} песня история".strip()
            ask = f"Расскажи о песне «{song}»" + (f" исполнителя {artist}" if artist else "")
        else:
            subject = artist or song
            query = f"{subject} исполнитель биография"
            ask = (f"Кто такой исполнитель {subject}? Начни с главного — кто это и чем известен, "
                   "потом назови одну-две самые известные песни. Без случайных подробностей.")
        bus.bus.log("system", f"ищу в интернете: {query}")
        said = False
        for piece in self._agent.answer_from_web(ask, query):
            said = True
            yield piece
        if not said:
            yield f"Сейчас играет {artist or song}, но в интернете ничего толком не нашла."

    def _look_once(self, question: str) -> str:
        """Вопрос про картинку вне звонка: прямо в модель зрения, без цикла агента.

        Раньше такой вопрос шёл в агента: модель думала, звала инструмент, модель
        зрения выталкивала её из видеопамяти, Ollama отвечала ошибкой нехватки
        памяти, шёл повтор — больше минуты. Здесь основная модель выгружается
        сразу, зрение отвечает за несколько секунд, а основная возвращается фоном.
        """
        from . import vision

        url = str(self._cfg["brain"].get("ollama_url", "http://127.0.0.1:11434"))
        model = vision.available_model(url)
        if model is None:
            return "Модель зрения не установлена: выполни ollama pull qwen2.5vl:3b."
        if not vision.unified(model):
            vision.free_vram(url, keep=model)
        prompt = (f"{question.strip()} Отвечай по-русски, коротко и по делу, двумя-тремя "
                  "предложениями, только о том, что реально видно.")
        try:
            answer = vision.describe(vision.grab_screen(), url, model, vision._prompt_for(model, prompt),
                                     timeout_s=60, num_predict=180, keep_alive="20s")
        finally:
            if not vision.unified(model):
                self._rewarm_agent()
        return answer.strip()

    def _on_sense(self, sensed) -> None:
        """Быстрое восприятие: запоминаем сцену и сразу замечаем ошибку на экране."""
        log = self._call_log
        if log is not None:
            log.saw(sensed.caption())
        if not self._cfg.get("live", {}).get("proactive", True):
            return
        evidence = " ".join((sensed.dialog, *sensed.fresh[:6]))
        if not evidence.strip() or not live.looks_like_trouble(evidence):
            return
        now = time.monotonic()
        if now - self._last_hint < float(self._cfg.get("live", {}).get("hint_gap_s", 90.0)):
            return
        if self._speech_lock.locked() or bus.bus.state == bus.THINKING:
            return
        self._last_hint = now
        seen = sensed.dialog or next((line for line in sensed.fresh if live.looks_like_trouble(line)), "")
        note = f"Вижу на экране: {seen[:160]}. Могу разобраться — спроси, что это."
        bus.bus.log("assistant", note)
        threading.Thread(target=self.say, args=(note,), name="jarvis-hint", daemon=True).start()

    def _on_scene(self, frame) -> None:
        """Новая сцена на экране: запоминаем и, если видно проблему, помогаем сами."""
        log = self._call_log
        if log is not None and frame.caption:
            log.saw(frame.caption)
        # разбор экрана вытеснил языковую модель из памяти видеокарты — возвращаем
        # её заранее, пока человек молчит, чтобы ответ не ждал загрузку весов
        self._rewarm_agent()

        if not self._cfg.get("live", {}).get("proactive", True) or not frame.caption:
            return
        if not live.looks_like_trouble(frame.caption):
            return
        now = time.monotonic()
        if now - self._last_hint < float(self._cfg.get("live", {}).get("hint_gap_s", 90.0)):
            return
        if self._speech_lock.locked() or bus.bus.state == bus.THINKING:
            return  # человек уже занят разговором — не перебиваем

        self._last_hint = now
        note = f"Вижу на экране: {frame.caption} Могу помочь — скажи, что сделать."
        bus.bus.log("assistant", note)
        threading.Thread(target=self.say, args=(note,), name="jarvis-hint", daemon=True).start()

    def _on_gesture(self, event) -> None:
        """Жест рукой — короткая команда без слов. Выполняется мгновенно, без модели."""
        from . import automation

        kind = event.kind
        try:
            if kind == "volume":
                automation.volume_set(event.value)
                bus.bus.log("system", f"жест: громкость {event.value}")
                return
            if kind == "ok":
                bus.bus.log("system", "жест: режим громкости — свожу и развожу пальцы")
                return
            if kind == "point":
                automation.media("play_pause")
                bus.bus.log("system", "жест: воспроизведение или пауза")
                self._short_reply("Музыка.")
                return
            if kind == "peace":
                automation.media("next")
                bus.bus.log("system", "жест: следующий трек")
                self._short_reply("Следующий.")
                return
            if kind == "palm":
                self.interrupt()
                automation.media("play_pause")
                bus.bus.log("system", "жест: тишина")
                return
            if kind == "three":
                # три пальца — показать или спрятать экранного компаньона
                bus.bus.publish({"type": "ui", "action": "toggle_companion"})
                bus.bus.log("system", "жест: панель компаньона")
                return
            if kind == "fist":
                muted = not self._muted.is_set()
                self.set_muted(muted)
                self._short_reply("Микрофон выключен." if muted else "Слушаю.")
                return
        except Exception as err:
            bus.bus.log("error", f"жест {kind}: {err}")

    def _short_reply(self, text: str) -> None:
        """Короткое подтверждение голосом, не блокируя поток камеры."""
        threading.Thread(target=self.say, args=(text,), name="jarvis-gesture-say", daemon=True).start()

    def _start_camera(self) -> None:
        """Камера включается вместе со звонком: открытие устройства идёт фоном."""
        settings = self._cfg.get("camera", {})
        if not settings.get("enabled", True) or self._camera is not None:
            return

        def open_camera() -> None:
            try:
                device = camera.Camera(
                    index=int(settings.get("index", 0)),
                    width=int(settings.get("width", 640)),
                    height=int(settings.get("height", 480)),
                    fps=float(settings.get("fps", 15.0)),
                    on_gesture=self._on_gesture if settings.get("gestures", True) else None,
                )
                device.start()
            except Exception as err:
                bus.bus.log("system", f"Камера недоступна: {str(err)[:120]}")
                return
            self._camera = device
            tools.camera_tools.configure(device, str(self._cfg["brain"].get("ollama_url", "")))
            tools.study_tools.set_camera(device)
            bus.bus.log("system", "Камера включена: вижу, кто передо мной.")

        threading.Thread(target=open_camera, name="jarvis-camera-start", daemon=True).start()

    def _stop_camera(self) -> None:
        device = self._camera
        self._camera = None
        tools.camera_tools.configure(None, str(self._cfg["brain"].get("ollama_url", "")))
        if device is not None:
            device.stop()

    @property
    def camera(self):
        return self._camera

    def start_live(self) -> str:
        """Включает видеорежим: слушает без обращения по имени и смотрит на экран."""
        if self._watcher is None:
            settings = self._cfg.get("live", {})
            self._watcher = live.Watcher(
                ollama_url=str(self._cfg["brain"].get("ollama_url", "http://127.0.0.1:11434")),
                preview_fps=float(settings.get("preview_fps", 8.0)),
                min_gap_s=float(settings.get("min_gap_s", 2.0)),
                idle_refresh_s=float(settings.get("idle_refresh_s", 30.0)),
                preview_side=int(settings.get("preview_side", 640)),
                analyze_side=int(settings.get("max_side", 512)),
            )
            self._watcher.on_frame = self._on_scene
            self._watcher.on_sense = self._on_sense
            self._call_log = live.CallLog()
            self._last_hint = time.monotonic()
            self._watcher.start()
            self._start_camera()
            # лёгкую модель греем заранее: иначе первый же ответ в звонке ждёт её загрузку
            threading.Thread(
                target=lambda: self._agent.quick("привет"), name="jarvis-fast-warmup", daemon=True
            ).start()
        bus.bus.log("system", "Видеорежим включён: слушаю без обращения и вижу экран.")
        return "Видеосвязь установлена. Вижу твой экран, слушаю."

    def stop_live(self) -> str:
        watcher = self._watcher
        log = self._call_log
        self._watcher = None
        self._call_log = None
        if watcher is not None:
            watcher.stop()
        self._stop_camera()
        bus.bus.log("system", "Видеорежим выключен.")

        summary = self._summarize_call(log)
        if summary:
            bus.bus.log("assistant", summary)
            return summary
        return "Отключаюсь."

    def _summarize_call(self, log) -> str:
        """Короткий итог звонка. Он же уходит в долгую память — разговор не пропадает."""
        if log is None or (not log.lines and not log.scenes) or log.minutes < 0.4:
            return ""
        if not self._agent.available():
            return ""
        try:
            summary = self._agent.ask(
                "Подведи итог видеозвонка одним-двумя предложениями: о чём говорили и что "
                f"было на экране. Без вступлений.\n\n{log.digest()}"
            )
        except Exception:
            return ""
        summary = summary.strip()
        if not summary:
            return ""
        try:
            from . import memory

            memory.remember(f"Видеозвонок {time.strftime('%d.%m %H:%M')}: {summary}", tag="звонки")
        except Exception:
            pass
        return f"Отключаюсь. {summary}"

    def screen_note(self) -> str:
        """Последнее описание экрана — для панели интерфейса."""
        return self._watcher.frame.caption if self._watcher is not None else ""

    def _directed(self, text: str, named: bool) -> bool:
        """Обращаются ли к ассистенту. Нужно в звонке, где имя произносить не требуется.

        Фоновая речь — видео, музыка, разговор в комнате — почти всегда начинается не с
        команды и не с вопроса. Поэтому реплика принимается, если назвали по имени,
        если разговор уже идёт, или если фраза начинается как команда либо вопрос.
        """
        if named:
            return True
        if time.monotonic() < self._open_until:
            return True  # диалог продолжается — отвечаем без формальностей

        clean = text_utils.normalize(text)
        if not clean:
            return False
        directed = bool(DIRECTED.match(clean))
        # односложные реплики принимаем только если это явная команда: «стоп», «дальше»
        return directed if len(clean.split()) < 2 else directed

    def _respond_stream(self, text: str, turn: int):
        """Быстрая точная команда, иначе — агент с инструментами.

        Ответ отдаётся кусками: синтез начинает говорить с первого готового
        предложения, а не после того, как модель допишет всё до конца.
        """
        clean = text_utils.normalize(text) or text

        # звонок — это окно интерфейса, его открывает и закрывает пульт
        if CALL_END.search(clean) and self._watcher is not None:
            bus.bus.publish({"type": "ui", "action": "end_call"})
            yield "Отключаюсь."
            return
        if CALL_START.search(clean) and self._watcher is None:
            bus.bus.publish({"type": "ui", "action": "start_call"})
            yield "Соединяю."
            return

        # «Замени» — готовый текст на место выделенного (после «переведи это», «перепиши вежливее»)
        from . import selection

        if selection.wants_replace(clean):
            try:
                yield selection.replace()
            except selection.SelectionError as err:
                yield f"{str(err)[:1].upper()}{str(err)[1:]}."
            return

        # «Вставь», «отправь второй», «другой вариант» — к предложенным ответам
        from . import replies

        picked = replies.handle_pick(clean)
        if picked is not None:
            yield picked
            return

        # «Что мне ему ответить?» — варианты ответа по переписке на экране
        if replies.wants_help(clean) and self._agent.available():
            yield from self._suggest_reply()
            return

        # «Переведи это», «объясни выделенное», «перепиши вежливее» — в любой программе
        selection_mode = selection.mode_of(clean)
        if selection_mode and self._agent.available():
            yield from self._on_selection(clean, selection_mode)
            return

        # «Что за ошибка?» — разбор ошибки в коде на экране
        from . import codehelp, coding

        if codehelp.wants_help(clean) and self._agent.available():
            yield from self._code_help(clean)
            return

        # «Напиши калькулятор» — агент-программист работает в фоне, вкладка «Агент» показывает ход

        # «Добавь в калькулятор тёмную тему» — доработка последнего проекта
        last = coding.history.last()
        if last and coding.wants_change(clean, str(last.get("title", ""))) and self._agent.available():
            yield self.start_code(clean, existing=Path(last["root"]))
            return
        if coding.wants_code(clean) and self._agent.available():
            yield self.start_code(clean)
            return

        # «Доброе утро» — брифинг; «что мне писали?» — сводка Telegram
        from . import briefing

        if self._agent.available() and briefing.wants_briefing(clean):
            yield from self._retell(clean, briefing.BRIEFING_PROMPT, "собираю сводку на день…",
                                    lambda: briefing.gather(with_news=True), 340)
            return
        if self._agent.available() and briefing.wants_inbox(clean):
            yield from self._retell(clean, briefing.INBOX_PROMPT, "читаю список чатов Telegram…",
                                    briefing.inbox_digest, 240)
            return

        # «Что скажешь об этом исполнителе?» — смотрим, что играет, и ищем в интернете
        playing = questions.about_playing(clean)
        if playing is not None:
            yield from self._about_playing(clean, playing)
            return

        # Вопрос про экран. Текст и структуру экрана читаем за треть секунды, а
        # отвечает основная модель — она уже в видеопамяти и умнее модели зрения.
        # Модель зрения зовём, только если нужны пиксели: картинка, видео, игра.
        # Не тогда, когда Юки ждёт текст сообщения: тогда фраза — это текст.
        watcher = self._watcher
        about_screen = live.wants_screen(clean) if watcher is not None else live.asks_about_screen(clean)
        if about_screen and not commands.pending_question():
            answered = False
            try:
                sensed = watcher.digest(fresh=True) if watcher is not None else live.sense_screen()
                if self._agent.available() and self._agent.sees:
                    # одна модель на всё: снимок и текст экрана в одном запросе, без перезагрузок
                    from . import vision

                    bus.bus.log("system", f"смотрю на экран: текст {sensed.spent_ms:.0f} мс + снимок")
                    for piece in self._agent.screen_stream(clean, sensed.digest(), image=vision.grab_screen()):
                        answered = True
                        yield piece
                elif live.needs_pixels(clean) or sensed.sparse:
                    bus.bus.log("system", "смотрю на картинку моделью зрения…")
                    if watcher is not None:
                        yield watcher.ask(clean)
                    else:
                        yield self._look_once(clean)
                    answered = True
                elif self._agent.available():
                    bus.bus.log("system", f"читаю экран: {sensed.spent_ms:.0f} мс")
                    for piece in self._agent.screen_stream(clean, sensed.digest()):
                        answered = True
                        yield piece
            except Exception as err:
                bus.bus.log("error", f"зрение: {err}")
            if answered:
                return

        # Быстрый путь выполняет всё, что умеет, а невыполненный хвост просьбы
        # отдаёт агенту. Раньше «открой ютуб и включи видео» с неудачной второй
        # половиной докладывало об успехе, и хвост молча пропадал.
        plan = commands.handle_plan(clean)
        if plan.answer and not plan.remainder:
            bus.bus.log("system", f"команда: {commands.match_intent(clean) or 'прямая'}")
            yield plan.answer
            return
        if plan.answer:
            bus.bus.log("system", f"сделано быстро: {plan.answer[:80]} — остаток агенту: {plan.remainder}")
            yield plan.answer + " "
            clean = plan.remainder
        direct = plan.failure

        if not self._agent.available():
            yield (
                direct
                or commands.fallback(clean)
                or "Модель не запущена: выполни ollama serve. Прямые команды работают."
            )
            return

        if direct is not None:
            bus.bus.log("system", f"прямая команда не удалась ({direct}) — беру инструменты")

        note = watcher.context() if watcher is not None else ""

        # Объяснить, разобрать, сравнить, написать код или план — развёрнутый ответ:
        # суть звучит голосом, разбор ложится на экран карточкой.
        if questions.deep_request(clean):
            bus.bus.log("system", "развёрнутый ответ")
            said = False
            for piece in self._expert(clean, note):
                said = True
                yield piece
            if said:
                return

        # Вопрос о мире — сразу в поиск, модель только пересказывает найденное.
        # Иначе он попадал в разговорный путь без инструментов, и модель уверенно
        # выдумывала цены, даты и биографии.
        query = questions.web_query(clean)
        if query is not None:
            bus.bus.log("system", f"ищу в интернете: {query}")
            said = False
            for piece in self._agent.answer_from_web(clean, query, context=note):
                said = True
                yield piece
            if said:
                return

        # Разговор и приказ — разные пути. Раньше быстрый путь работал только в
        # режиме звонка, и «привет, как ты?» шло в большую модель с полусотней
        # инструментов: она думала секунды и норовила что-нибудь запустить.
        # Теперь простая реплика уходит разговорной модели без инструментов — она
        # отвечает быстро и физически не может открыть или закрыть программу.
        if _is_small_talk(clean):
            bus.bus.log("system", "разговор")
            said = False
            for piece in self._agent.quick_stream(clean, context=note):
                said = True
                yield piece
            if said:
                return

        question = f"{clean}\n\n[{note}]" if note else clean
        yield from self._agent.run_stream(
            question, on_step=self._on_step,
            should_stop=lambda: self._cancelled(turn),
        )

    def _on_selection(self, question: str, mode: str):
        """Выделенный текст: объяснение — голосом и разбором, остальное — готовым текстом и «замени»."""
        from . import selection

        try:
            text, hwnd = selection.grab()
        except selection.SelectionError as err:
            yield f"{str(err)[:1].upper()}{str(err)[1:]}."
            return
        bus.bus.log("system", f"выделено {len(text)} знаков")
        prompt = agent_module._persona(selection.PROMPTS[mode])
        if mode == "explain":
            stream = self._agent.generate(prompt, text, num_predict=900, temperature=0.3)
            yield from self._expert(question, "", stream=stream)
            return
        result = "".join(self._agent.generate(prompt, text, num_predict=1400, temperature=0.3)).strip()
        if not result:
            yield "Не получилось — попробуй ещё раз."
            return
        selection.remember(hwnd, mode, result)
        title = selection.SPOKEN.get(mode, "Готово")
        bus.bus.publish({"type": "message", "kind": "report",
                         "text": f"## {title}\n{result}\n\n> Скажи «замени» — поставлю на место выделенного."})
        if len(result) <= 220:
            yield f"{title}: {result} Сказать «замени» — поставлю на место."
        else:
            yield f"{title} готов, он в «Диалоге». Скажи «замени» — поставлю на место выделенного."

    def _code_help(self, question: str):
        """Ошибка в коде на экране: причина — голосом, разбор — карточкой, исправление — в буфер."""
        from . import automation, codehelp, replies

        bus.bus.log("system", "читаю ошибку на экране и думаю…")
        # размышление занимает полминуты — молчать всё это время нельзя
        yield "Смотрю ошибку, дай подумать. "
        window = replies.target_window()
        screen_text, image = replies.read_chat(window)
        found: list[str] = []
        stream = self._agent.code_help_stream(question, screen_text.replace("Текст переписки", "Текст окна"), image)
        yield from self._expert(question, "", stream=stream, on_details=found.append)
        fix = codehelp.first_code(found[0]) if found else ""
        if fix:
            try:
                automation.set_clipboard(fix)
                yield " Исправленный код в буфере обмена — вставь через Ctrl+V."
            except Exception:
                pass

    def _expert(self, question: str, note: str, stream=None, on_details=None):
        """Отдаёт голосу только суть, а весь разбор публикует карточкой.

        Модель пишет первой строкой суть, затем пустую строку и markdown. Если она
        формат не соблюла, суть обрезается сама: два предложения или ~260 знаков.
        `stream` — готовый поток вместо обычного экспертного ответа.
        """
        spoken: list[str] = []
        rest: list[str] = []
        speaking = True
        source = stream if stream is not None else self._agent.expert_stream(question, context=note)
        for piece in source:
            if not speaking:
                rest.append(piece)
                continue
            spoken.append(piece)
            text = "".join(spoken)
            cut = _gist_cut(text)
            if cut is None:
                continue
            speaking = False
            head, tail = text[:cut], text[cut:]
            if head.strip():
                yield _speakable(head)
            rest.append(tail)
        if speaking:
            text = "".join(spoken)
            yield _speakable(text[:_gist_cut(text, final=True) or len(text)])
            rest.append(text[_gist_cut(text, final=True) or len(text):])
        details = "".join(rest).strip()
        if on_details is not None:
            on_details(details)
        if len(details) > 40:
            bus.bus.publish({"type": "message", "kind": "report", "text": details})
            yield " Подробности на экране."

    # ---------------------------------------------------------------- речь

    def interrupt(self) -> None:
        """Обрывает текущую реплику — новая команда важнее того, что он договаривает.

        Счётчик вместо флага: если «замолчи» прилетело за миг до начала реплики,
        флаг успевал сброситься и команда терялась. Номер поколения потеряться не может.
        """
        with self._speech_guard:
            self._speech_epoch += 1
        self._speech_stop.set()

    @contextlib.contextmanager
    def _conversation(self):
        """Пока Юки отвечает человеку, агент-программист не занимает модель."""
        with self._talk_lock:
            self._talking += 1
        try:
            yield
        finally:
            with self._talk_lock:
                self._talking -= 1
                self._quiet_since = time.monotonic()
                self._talk_lock.notify_all()

    def _wait_quiet(self, pause_s: float = 4.0) -> None:
        """Ждёт, пока разговор стихнет: человек часто задаёт следующий вопрос сразу."""
        with self._talk_lock:
            while self._talking > 0 or time.monotonic() - self._quiet_since < pause_s:
                self._talk_lock.wait(timeout=0.5)

    def start_code(self, task: str, existing=None, parent=None) -> str:
        """Запускает агента-программиста; о готовности Юки скажет сама."""
        if self.coder.busy:
            return "Я ещё пишу прошлый проект. Скажи «стоп», если он больше не нужен."
        started = self.coder.start(task, on_done=self._code_done, parent=parent, existing=existing)
        if not started:
            return "Я ещё пишу прошлый проект."
        bus.bus.publish({"type": "ui", "action": "open_section", "section": "agent"})
        if existing is not None:
            return f"Дорабатываю «{Path(existing).name}». Скажу, когда проверю."
        return ("Берусь. Сначала продумаю план, потом напишу код, тесты и сама всё проверю — "
                "ход работы во вкладке «Агент».")

    def _code_done(self, summary: str) -> None:
        bus.bus.publish({"type": "message", "kind": "report", "text": f"## Агент\n{summary}"})
        # путь к папке читать вслух незачем — он в «Диалоге» и во вкладке
        self.say(re.sub(r"Папка .*?, файлы: .*$", "Открыла, пробуй.", summary))

    def say(self, text: str) -> None:
        if text.strip():
            self.say_stream(iter((text,)))

    def _cancelled(self, turn: int) -> bool:
        """Отменена ли работа этого хода.

        Номер хода — главный признак. Флаг «стоп» снимается в начале следующей
        реплики, и полагаться только на него нельзя: старый поток успевал увидеть
        уже очищенный флаг и продолжал выполнять шаги поверх новой просьбы.
        """
        return self._stop.is_set() or self._turn != turn or self._speech_stop.is_set()

    def _with_filler(self, pieces, turn: int):
        """Отвечает коротким «секунду», если ответ задерживается дольше обычного.

        Человек, задавший вопрос в тишину, через две секунды считает, что его не
        услышали. Живой собеседник в этом месте говорит «сейчас посмотрю» — и
        пауза перестаёт быть неловкой. Заготовка звучит мгновенно: она уже лежит
        в кэше синтеза, поэтому ничего не стоит.

        Ответ считается в отдельном потоке, поэтому его обязательно нужно уметь
        остановить. Иначе «стоп» затыкал только голос: невидимый поток продолжал
        выполнять оставшиеся шаги — открывал окна и печатал текст уже после того,
        как человек всё отменил, а следующая просьба шла поверх незаконченной.
        """
        import queue as queue_module

        # Очередь без предела намеренно. Ограниченная означала бы, что поток
        # застрянет на `put`, если слушателя уже нет — а он пропадает всякий раз,
        # когда речь оборвали или монолог упёрся в предел длины. Объём безопасен:
        # длину ответа ограничивает сама модель через num_predict.
        box: queue_module.Queue = queue_module.Queue()
        # Слушатель может исчезнуть и без отмены хода: синтез обрывает слишком
        # длинный монолог на границе предложения и просто перестаёт читать. Без
        # этого признака поток продолжал крутить цикл агента для ответа, который
        # уже никто не услышит, — и доделывал шаги вхолостую.
        dropped = threading.Event()

        def pump() -> None:
            try:
                for piece in pieces:
                    if dropped.is_set() or self._cancelled(turn):
                        break
                    box.put(("text", piece))
            except Exception as err:
                box.put(("error", err))
            finally:
                closer = getattr(pieces, "close", None)
                if closer is not None:
                    closer()  # обрывает цикл агента: следующий шаг не начнётся
                box.put(("end", None))

        worker = threading.Thread(target=pump, name="jarvis-answer", daemon=True)
        worker.start()

        filled = False
        # Потолок ожидания. Инструмент, зависший навсегда (окно не отвечает, сеть
        # молчит), иначе оставил бы ассистента немым: голосовой цикл ждал бы его
        # вечно и не принимал бы новых просьб. Лучше признаться и слушать дальше.
        deadline = time.monotonic() + _ANSWER_LIMIT_S
        try:
            while True:
                try:
                    kind, value = box.get(timeout=_FILLER_AFTER_S if not filled else 0.25)
                except queue_module.Empty:
                    if self._cancelled(turn):
                        return
                    if time.monotonic() > deadline:
                        bus.bus.log("error", "ответ не пришёл вовремя — снимаю задачу")
                        yield "Что-то застряло, я это бросила. Скажи ещё раз?"
                        return
                    if not filled:
                        filled = True
                        yield random.choice(_FILLERS) + " "
                    continue
                if kind == "end":
                    return
                if kind == "error":
                    raise value
                yield value
        finally:
            dropped.set()

    def say_stream(self, pieces) -> str:
        """Произносит ответ по мере его появления и возвращает сказанное целиком.

        Речь начинается с первого законченного предложения, поэтому пауза между
        вопросом и голосом равна времени генерации одной фразы, а не всего ответа.
        """
        from . import persona

        voice = self._voice
        collected: list[str] = []
        pieces = persona.stream_fix(pieces)  # мужской голос говорит о себе в мужском роде

        def tracked():
            for piece in pieces:
                if piece:
                    if not collected:
                        # состояние переключаем на первом же куске текста: до него
                        # ассистент ещё думает, и «говорит» в интерфейсе было бы враньём
                        bus.bus.set_state(bus.SPEAKING)
                        self._speech_started = time.monotonic()
                    collected.append(piece)
                    self._feel(collected)
                    yield piece

        if voice is None:
            self._last_answer = text_utils.clean_reply("".join(tracked()))
            return self._last_answer

        with self._speech_lock:
            with self._speech_guard:
                epoch = self._speech_epoch
            # Отмену здесь уже не снимаем: реплика могла простоять в очереди за
            # предыдущей, и прилетевший за это время «стоп» относится и к ней.
            self._mood_sent = False

            def cancelled() -> bool:
                return self._stop.is_set() or self._speech_epoch != epoch

            # пока ответ считается, перебить нечего — отсчёт начнётся с первого слова
            self._speech_started = float("inf")
            try:
                voice.say_stream(tracked(), should_stop=cancelled,
                                 on_level=self._on_output_level, on_viseme=self._on_viseme)
            except Exception as err:
                bus.bus.log("error", f"TTS: {err}")
                # синтез отвалился — текст всё равно дочитываем из модели,
                # иначе ответ пропадёт и из журнала, и из памяти разговора
                for _ in tracked():
                    pass
            finally:
                # После перебивания хвост эха не нужен: она замолчала сама, эху
                # взяться неоткуда. Ждать его — значит проглотить начало фразы,
                # ради которой её и перебили.
                self._deaf_until = 0.0 if self._barged else time.monotonic() + _ECHO_TAIL_S
                self._barged = False
                bus.bus.set_level(0.0)
                self._last_answer = text_utils.clean_reply("".join(collected))
        return self._last_answer

    def _feel(self, spoken: list[str]) -> None:
        """Показывает реплику и настроение персонажа, пока она ещё произносится.

        Готовый текст попадает в журнал только после того, как отзвучал, поэтому
        субтитры и выражение лица опаздывали на целую фразу — персонаж говорил с
        каменным лицом, а подпись появлялась к моменту, когда он уже замолчал.
        Здесь и то и другое уходит в интерфейс по ходу речи.
        """
        text = "".join(spoken)
        now = time.monotonic()
        if now - self._last_caption > _CAPTION_GAP_S or text.endswith((".", "!", "?")):
            self._last_caption = now
            bus.bus.publish({"type": "speech", "text": text_utils.clean_reply(text)})

        if self._mood_sent:
            return
        # Заготовка «секунду» — не настроение ответа, а затычка паузы. Пока кроме
        # неё ничего не сказано, судить не о чем: иначе лицо застывало задумчивым
        # на всю реплику, каким бы радостным ни оказался сам ответ.
        meaning = text
        for filler in _FILLERS:
            if meaning.startswith(filler):
                meaning = meaning[len(filler):].strip()
                break
        if not meaning or (len(meaning) < 12 and not meaning.endswith((".", "!", "?"))):
            return  # слишком мало слов, чтобы судить о настроении
        self._mood_sent = True
        key = mood.of(meaning)
        bus.bus.publish({"type": "emotion", "key": key,
                         "shape": mood.dimensional(key), "seconds": 2.6})

    def _apply_configured_voice(self) -> None:
        """Ставит голос из настроек.

        Раздел синтеза важнее раздела персонажа: именно туда пишется выбор,
        сделанный голосом или в интерфейсе. Когда первым читался «companion»,
        выбранный голос жил до перезапуска и откатывался обратно.
        """
        voice = self._voice
        if voice is None:
            return
        wanted = (str(self._cfg.get("tts", {}).get("voice", "")).strip()
                  or str(self._cfg.get("companion", {}).get("voice", "")).strip())
        if not wanted:
            return
        try:
            profile = voices.resolve(wanted)
            if profile is not None and voice.profile is not profile:
                voice.set_profile(profile)
                bus.bus.log("system", f"Голос: {profile.title} ({profile.character}).")
        except Exception as err:
            bus.bus.log("error", f"Голос «{wanted}» не поставился: {err}")

    def greet(self, text: str, timeout: float = 90.0) -> None:
        """Произносит приветствие, когда синтез готов, и не задерживает запуск.

        Ждать приходится по-настоящему: модель голоса поднимается несколько
        секунд, и фраза, сказанная раньше, не прозвучит вовсе.
        """
        if not text.strip():
            return

        def run() -> None:
            if self.voice_ready.wait(timeout) and not self._stop.is_set():
                self.say(text)

        threading.Thread(target=run, name="jarvis-greeting", daemon=True).start()

    # ---------------------------------------------------------------- ввод текстом

    # ---------------------------------------------------------------- голоса

    @property
    def voice_key(self) -> str:
        """Ключ текущего голоса — интерфейс подсвечивает им активный пункт списка.

        Пока синтез не поднялся, отвечаем голосом из настроек, а не общим
        умолчанием: умолчание — мужской ДЖАРВИС, и первые секунды после запуска
        интерфейс показывал именно его, хотя выбран был женский.
        """
        voice = self._voice
        profile = voice.profile if voice is not None else None
        if profile is not None:
            return profile.key
        wanted = (str(self._cfg.get("tts", {}).get("voice", "")).strip()
                  or str(self._cfg.get("companion", {}).get("voice", "")).strip())
        return wanted or voices.DEFAULT

    def _quiet_swap(self, profile: voices.Profile) -> None:
        """Меняет голос, дождавшись конца текущей реплики: нельзя рвать поток на середине."""
        voice = self._voice
        if voice is None:
            raise tts.SynthesisError("синтез речи не запущен")
        self.interrupt()
        deadline = time.monotonic() + 2.0
        while voice.speaking and time.monotonic() < deadline:
            time.sleep(0.05)
        voice.set_profile(profile)

    def set_voice(self, name: str) -> str:
        """Переключает голос насовсем: выбор сохраняется в config.json."""
        try:
            profile = voices.resolve(name)
            self._quiet_swap(profile)
        except (voices.VoiceError, tts.SynthesisError) as err:
            bus.bus.log("error", str(err))
            self.say(str(err))
            return str(err)

        voices.remember(profile)
        answer = f"Голос {profile.title}. {profile.character.capitalize()}."
        bus.bus.log("system", f"Голос переключён: {profile.title} ({profile.model_name})")
        bus.bus.log("assistant", answer)
        self.say(answer)
        return answer

    def _preview_profile(self, profile: voices.Profile) -> str:
        """Даёт послушать голос и возвращает прежний — выбор не меняется."""
        previous = self._voice.profile if self._voice is not None else None
        self._quiet_swap(profile)
        bus.bus.log("system", f"Проба голоса: {profile.title}")
        self.say(profile.sample)
        if previous is not None and previous.key != profile.key:
            try:
                self._quiet_swap(previous)
            except tts.SynthesisError:
                pass
        return profile.sample

    def preview_voice(self, name: str) -> str:
        try:
            return self._preview_profile(voices.resolve(name))
        except (voices.VoiceError, tts.SynthesisError) as err:
            bus.bus.log("error", str(err))
            return str(err)

    def handle_text(self, text: str) -> None:
        """Ввод текстом из UI — тот же путь, минус распознавание."""
        clean = text.strip()
        if not clean:
            return
        self.interrupt()
        if STOP_WORDS.match(clean):
            bus.bus.set_state(bus.LISTENING)
            return
        # реплику мог ждать кто-то другой — например, диктовка текста сообщения
        catcher = self._take_catcher()
        if catcher is not None:
            bus.bus.log("user", clean)
            try:
                catcher(clean)
            except Exception as err:
                bus.bus.log("error", f"диктовка: {err}")
            bus.bus.set_state(bus.LISTENING)
            return

        bus.bus.log("user", clean)
        self._turn += 1
        # Отмену снимаем ровно один раз за ход. Делать это в say_stream было
        # нельзя: напоминание или приветствие, прозвучавшее сразу после «стоп»,
        # снимало флаг и воскрешало уже отменённый цикл агента.
        self._speech_stop.clear()
        bus.bus.set_state(bus.THINKING)
        turn = self._turn
        with self._conversation():
            answer = self.say_stream(self._with_filler(self._respond_stream(clean, turn), turn))
        bus.bus.log("assistant", answer)
        self._open_until = time.monotonic() + FOLLOW_UP_S
        self._learn(clean, answer)
        bus.bus.set_state(bus.LISTENING)

    # ---------------------------------------------------------------- перехват реплики

    def capture_next(self, handler, timeout_s: float = 60.0) -> None:
        """Следующая фраза человека уйдёт этому получателю, а не агенту.

        Так работает диктовка: Юки спросила «что написать», и услышанное должно
        стать текстом сообщения целиком — без разбора на команды и без попытки
        что-то выполнить.
        """
        with self._catch_lock:
            self._catcher = (handler, time.monotonic() + max(5.0, timeout_s))

    def _take_catcher(self):
        """Забирает получателя реплики, если он ещё ждёт и не просрочен."""
        with self._catch_lock:
            item = self._catcher
            if item is None:
                return None
            handler, until = item
            self._catcher = None
        return handler if time.monotonic() <= until else None

    def cancel_capture(self) -> None:
        with self._catch_lock:
            self._catcher = None

    def reset(self) -> None:
        self._agent.reset()
        bus.bus.log("system", "Контекст разговора очищен.")

    # ---------------------------------------------------------------- личная память

    def _learn(self, question: str, answer: str) -> None:
        """Запоминает факты о человеке из обычного разговора, а не только по команде.

        Раньше память пополнялась исключительно словом «запомни». Человек мог
        десять раз сказать, где работает и как зовут его кота, — назавтра
        ассистент не помнил ничего. Разбор идёт фоном и только на фразах, похожих
        на рассказ о себе: лишние обращения к модели заняли бы видеокарту.
        """
        if not PERSONAL.search(question or "") or len(question.strip()) < 8:
            return
        now = time.monotonic()
        if now - self._last_learn < _LEARN_GAP_S:
            return
        self._last_learn = now
        turn = self._turn

        def extract() -> None:
            from . import memory

            # Ollama выполняет запросы по одному. Разбор, начатый в тот момент,
            # когда человек уже задал следующий вопрос, встал бы перед ним в
            # очередь и добавил секунду к ответу. Ждём паузу и проверяем, что
            # разговор не ушёл дальше.
            time.sleep(_LEARN_DELAY_S)
            if self._stop.is_set() or self._turn != turn or self._speech_lock.locked():
                return
            try:
                raw = self._agent.ask(
                    "Из реплики пользователя выпиши факты о нём самом, которые стоит помнить "
                    "долго: имя, возраст, город, работа, учёба, близкие, питомцы, увлечения, "
                    "устойчивые предпочтения. Каждый факт — отдельная строка от третьего лица, "
                    "например «Живёт в Обнинске». Не больше четырёх строк. Ничего не выдумывай "
                    "и ничего не поясняй: только строки с фактами. Если фактов нет, ответь "
                    "одним словом НЕТ.\n\nРеплика: " + question.strip(),
                    num_predict=90,
                )
            except Exception:
                return
            for fact in _facts_from(raw):
                try:
                    memory.remember(fact, tag="о человеке")
                    bus.bus.log("system", f"запомнил: {fact[:90]}")
                except ValueError:
                    continue

        threading.Thread(target=extract, name="jarvis-learn", daemon=True).start()
