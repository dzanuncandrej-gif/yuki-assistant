"""Содержимое разделов меню.

Каждая страница собирается из карточек и строк, а её элементы сразу привязаны к
хранилищу настроек: поменял переключатель — значение ушло в config.json и в
работающий ассистент. Ничего «применить» нажимать не нужно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import autostart as autostart_mod
from core import i18n, voices

from .. import webassets
from .controls import Card, input_row, select_row, slider_row, toggle_row
from .quicklaunch import quick_launch_card
from .settings import SettingsStore


def _noop(*_: object) -> None:
    return None


@dataclass
class Actions:
    """Что меню умеет попросить у приложения. По умолчанию — ничего не делать."""

    apply_voice: Callable[[str], None] = _noop
    preview_voice: Callable[[str], None] = _noop
    toggle_companion: Callable[[bool], None] = _noop
    companion_updated: Callable[[], None] = _noop
    reset_context: Callable[[], None] = _noop
    say_test: Callable[[str], None] = _noop
    diagnostics: Callable[[], str] = lambda: ""
    extras: dict[str, Callable[..., None]] = field(default_factory=dict)


def _page(*cards: QWidget) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 8, 0)
    layout.setSpacing(14)
    for card in cards:
        layout.addWidget(card)
    layout.addStretch(1)
    return page


def _action(text: str, handler: Callable[[], None], ghost: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("menuGhost" if ghost else "menuAction")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda: handler())
    return button


def _buttons(*items: QWidget) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 6, 0, 0)
    row.setSpacing(8)
    for item in items:
        row.addWidget(item)
    row.addStretch(1)
    return holder


# ---------------------------------------------------------------- голос


def voice_page(store: SettingsStore, actions: Actions) -> QWidget:
    catalog = voices.catalog()
    items = [
        (profile.key, f"{profile.title} · {profile.character}"
         + ("" if profile.installed else "  " + i18n.t("(модель не скачана)")))
        for profile in catalog
    ]

    card = Card(i18n.t("Голос ассистента"), i18n.t("Тембр, которым Юки говорит вслух."))
    row, box = select_row(i18n.t("Профиль голоса"),
                          i18n.t("Silero держит все голоса в одной модели — переключение мгновенное."),
                          items, str(store.get("tts", "voice", voices.DEFAULT)))
    box.currentIndexChanged.connect(
        lambda: (store.set("tts", "voice", box.currentData()), actions.apply_voice(str(box.currentData())))
    )
    card.add(row)

    engine_row, engine = select_row(
        i18n.t("Движок синтеза"), i18n.t("auto выбирает лучший доступный: Silero → Piper → Edge → системный."),
        [("auto", i18n.t("АВТОМАТИЧЕСКИ")), ("silero", i18n.t("SILERO · офлайн")), ("piper", i18n.t("PIPER · офлайн")),
         ("edge", i18n.t("EDGE · сеть")), ("pyttsx3", i18n.t("СИСТЕМНЫЙ"))],
        str(store.get("tts", "engine", "auto")),
    )
    engine.currentIndexChanged.connect(lambda: store.set("tts", "engine", engine.currentData()))
    card.add(engine_row)

    gain_row, gain, _ = slider_row(i18n.t("Громкость речи"), i18n.t("Уровень голоса относительно системного."),
                                   float(store.get("tts", "voice_gain", 1.0)) * 100, 40, 160)
    gain.valueChanged.connect(lambda value: store.set("tts", "voice_gain", round(value / 100.0, 2)))
    card.add(gain_row)

    card.add(_buttons(
        _action(i18n.t("ПОСЛУШАТЬ"), lambda: actions.preview_voice(str(box.currentData()))),
        _action(i18n.t("ТЕСТОВАЯ ФРАЗА"),
                lambda: actions.say_test(i18n.t("Проверка голоса. Я слышу тебя и готова помочь.")), ghost=True),
    ))

    listening = Card(i18n.t("Слух"), i18n.t("Как Юки слушает микрофон."))
    wake_row, wake = toggle_row(i18n.t("Обращение по имени"), i18n.t("Реагировать только после слова «Юки»."),
                                bool(store.get("wake", "enabled", False)))
    wake.toggled.connect(lambda value: store.set("wake", "enabled", value))
    listening.add(wake_row)

    neural_row, neural = toggle_row(i18n.t("Нейронный детектор речи"),
                                    i18n.t("Silero VAD вместо порога громкости — меньше ложных срабатываний."),
                                    bool(store.get("audio", "neural_vad", True)))
    neural.toggled.connect(lambda value: store.set("audio", "neural_vad", value))
    listening.add(neural_row)

    silence_row, silence, _ = slider_row(i18n.t("Пауза до конца фразы, мс"),
                                         i18n.t("Сколько тишины считать окончанием реплики."),
                                         float(store.get("audio", "silence_ms", 620)), 300, 1500)
    silence.valueChanged.connect(lambda value: store.set("audio", "silence_ms", int(value)))
    listening.add(silence_row)

    return _page(card, listening)


# ---------------------------------------------------------------- язык


def language_page(store: SettingsStore, actions: Actions) -> QWidget:
    card = Card(i18n.t("Язык интерфейса"), i18n.t("На каком языке говорит меню и подписи."))
    row, box = select_row(i18n.t("Язык"), i18n.t("Пока доступны русский и английский."),
                          [("ru", i18n.t("РУССКИЙ")), ("en", "ENGLISH")], str(store.get("ui", "language", "ru")))
    box.currentIndexChanged.connect(lambda: store.set("ui", "language", box.currentData()))
    card.add(row)

    lang_note = QLabel(i18n.t("Меню и подписи обновятся при следующем запуске Юки."))
    lang_note.setObjectName("rowHint")
    lang_note.setWordWrap(True)
    card.add(lang_note)

    speech = Card(i18n.t("Язык распознавания"), i18n.t("Что Юки ожидает услышать в микрофоне."))
    stt_row, stt = select_row(i18n.t("Речь"), i18n.t("Автоматический режим медленнее, но понимает обе речи."),
                              [("ru", i18n.t("РУССКИЙ")), ("en", "ENGLISH"), ("auto", i18n.t("АВТОМАТИЧЕСКИ"))],
                              str(store.get("stt", "language", "ru")))

    def set_stt_language() -> None:
        code = str(stt.currentData())
        store.set("stt", "language", code)
        try:
            from core import language as speech_language

            if code in speech_language.LANGUAGES:
                speech_language.set_active(code)
        except Exception:  # noqa: BLE001 — ассистент мог ещё не запуститься
            pass

    stt.currentIndexChanged.connect(set_stt_language)
    speech.add(stt_row)

    model_row, model = select_row(i18n.t("Модель распознавания"),
                                  i18n.t("Крупнее модель — точнее слова, но выше задержка."),
                                  [("tiny", i18n.t("TINY · самая быстрая")), ("base", "BASE"),
                                   ("small", i18n.t("SMALL · баланс")),
                                   ("medium", "MEDIUM"), ("large-v3-turbo", i18n.t("LARGE V3 TURBO · точная"))],
                                  str(store.get("stt", "model_size", "small")))
    model.currentIndexChanged.connect(lambda: store.set("stt", "model_size", model.currentData()))
    speech.add(model_row)

    lexicon_row, lexicon = toggle_row(i18n.t("Словарь исправлений"),
                                      i18n.t("Подгоняет расслышанные слова под имена программ и контактов."),
                                      bool(store.get("stt", "lexicon", True)))
    lexicon.toggled.connect(lambda value: store.set("stt", "lexicon", value))
    speech.add(lexicon_row)

    note = QLabel(i18n.t("Смена модели распознавания применяется при следующем запуске Юки."))
    note.setObjectName("rowHint")
    note.setWordWrap(True)
    speech.add(note)

    return _page(card, speech)


# ---------------------------------------------------------------- интеллект


def ai_page(store: SettingsStore, actions: Actions) -> QWidget:
    card = Card(i18n.t("Модель"), i18n.t("Мозг ассистента: локальная Ollama."))
    model_row, model = input_row(i18n.t("Основная модель"),
                                 i18n.t("Например qwen3:8b — используется для сложных ответов."),
                                 str(store.get("brain", "model", "qwen3:8b")), "qwen3:8b")
    model.editingFinished.connect(lambda: store.set("brain", "model", model.text().strip()))
    card.add(model_row)

    fast_row, fast = input_row(
        i18n.t("Быстрая модель"),
        i18n.t(
            "Отдельная лёгкая модель для болтовни. Пусто — разговор ведёт основная, и это "
            "обычно быстрее: две модели не помещаются в память видеокарты вместе и "
            "выгружают друг друга при каждом переключении."
        ),
        str(store.get("brain", "fast_model", "")), i18n.t("не задана"),
    )
    fast.editingFinished.connect(lambda: store.set("brain", "fast_model", fast.text().strip()))
    card.add(fast_row)

    url_row, url = input_row(i18n.t("Адрес Ollama"), i18n.t("Где крутится сервер моделей."),
                             str(store.get("brain", "ollama_url", "http://127.0.0.1:11434")))
    url.editingFinished.connect(lambda: store.set("brain", "ollama_url", url.text().strip()))
    card.add(url_row)

    behaviour = Card(i18n.t("Поведение"), i18n.t("Насколько свободно Юки рассуждает."))
    temp_row, temp, _ = slider_row(i18n.t("Творческая свобода"), i18n.t("Ниже — строже и предсказуемее ответы."),
                                   float(store.get("brain", "temperature", 0.3)) * 100, 0, 100)
    temp.valueChanged.connect(lambda value: store.set("brain", "temperature", round(value / 100.0, 2)))
    behaviour.add(temp_row)

    history_row, history, _ = slider_row(i18n.t("Память диалога, реплик"),
                                         i18n.t("Сколько прошлых реплик держать в контексте."),
                                         float(store.get("brain", "history_turns", 8)), 2, 24)
    history.valueChanged.connect(lambda value: store.set("brain", "history_turns", int(value)))
    behaviour.add(history_row)

    think_row, think = toggle_row(
        i18n.t("Показывать размышления"),
        i18n.t("Модель проговаривает ход мысли в журнале. Ответ становится в разы медленнее — включать только для отладки."),
        bool(store.get("brain", "think", False)),
    )
    think.toggled.connect(lambda value: store.set("brain", "think", value))
    behaviour.add(think_row)

    proactive_row, proactive = toggle_row(i18n.t("Инициатива в звонке"),
                                          i18n.t("Сам предлагает помощь, увидев ошибку на экране."),
                                          bool(store.get("live", "proactive", True)))
    proactive.toggled.connect(lambda value: store.set("live", "proactive", value))
    behaviour.add(proactive_row)

    behaviour.add(_buttons(
        _action(i18n.t("ОЧИСТИТЬ КОНТЕКСТ"), actions.reset_context, ghost=True),
    ))

    senses = Card(i18n.t("Зрение и жесты"), i18n.t("Камера включается вместе с режимом видеосвязи."))
    camera_row, camera = toggle_row(i18n.t("Камера"), i18n.t("Узнаёт лицо и держит взгляд персонажа."),
                                    bool(store.get("camera", "enabled", True)))
    camera.toggled.connect(lambda value: store.set("camera", "enabled", value))
    senses.add(camera_row)

    gestures_row, gestures = toggle_row(i18n.t("Управление жестами"),
                                        i18n.t("Пальцы управляют музыкой, громкостью и панелью."),
                                        bool(store.get("camera", "gestures", True)))
    gestures.toggled.connect(lambda value: store.set("camera", "gestures", value))
    senses.add(gestures_row)

    return _page(card, quick_launch_card(store), behaviour, senses)


# ---------------------------------------------------------------- персонаж


def character_page(store: SettingsStore, actions: Actions) -> QWidget:
    main = Card(i18n.t("Экранный компаньон"), i18n.t("Живой персонаж на рабочем столе: мимика, взгляд, голос."))
    enabled_row, enabled = toggle_row(i18n.t("Показывать персонажа"), i18n.t("Панель с персонажем поверх окон."),
                                      bool(store.get("companion", "enabled", True)))
    main.add(enabled_row)

    # список собран из ui3d/characters: новая модель появляется здесь сама
    roster = webassets.characters()
    model = None
    if roster:
        model_items = [
            (str(item["id"]), f"{item.get('name', item['id'])}"
             + (f" · {item['subtitle']}" if item.get("subtitle") else ""))
            for item in roster
        ]
        current = str(store.get("companion", "character", model_items[0][0]))
        if current not in {key for key, _ in model_items}:
            current = model_items[0][0]
        model_row, model = select_row(
            i18n.t("Модель персонажа"),
            i18n.t("Трёхмерная фигура со скелетом и мимикой. Стоит на рабочем столе отдельным окном."),
            model_items, current,
        )
        main.add(model_row)

    name_row, name = input_row(i18n.t("Имя"), i18n.t("Как обращаться к персонажу."),
                               str(store.get("companion", "name", "Мира")), "Мира")
    name.editingFinished.connect(lambda: store.set("companion", "name", name.text().strip() or "Мира"))
    main.add(name_row)

    voice_items = [
        (profile.key, f"{profile.title} · {profile.character}")
        for profile in voices.catalog() if profile.key in voices.COMPANION_KEYS
    ]
    # Показываем тот голос, которым она говорит на самом деле. Раздел синтеза
    # главнее: выбор, сделанный голосом или на странице «Голос», пишется туда, и
    # страница персонажа показывала устаревшее имя, пока её не трогали руками.
    current_voice = (str(store.get("tts", "voice", "")).strip()
                     or str(store.get("companion", "voice", "mira")))
    voice_row, voice = select_row(i18n.t("Голос персонажа"), i18n.t("Женские живые голоса с аниме-интонацией."),
                                  voice_items, current_voice)
    main.add(voice_row)

    look = Card(i18n.t("Внешний вид"), i18n.t("Размер, план и прозрачность фигуры на экране."))
    framing_row, framing = select_row(
        i18n.t("План"), i18n.t("Насколько близко камера держит персонажа."),
        [("full", i18n.t("В ПОЛНЫЙ РОСТ")), ("bust", i18n.t("ПО ПОЯС")), ("close", i18n.t("КРУПНО · ЛИЦО"))],
        str(store.get("companion", "framing", "full")),
    )
    look.add(framing_row)

    quality_row, quality = select_row(
        i18n.t("Качество картинки"), i18n.t("Ниже — меньше нагрузка на видеокарту."),
        [("high", i18n.t("ВЫСОКОЕ")), ("medium", i18n.t("СРЕДНЕЕ")), ("low", i18n.t("ЛЁГКОЕ"))],
        str(store.get("companion", "quality", "high")),
    )
    look.add(quality_row)

    scale_row, scale, _ = slider_row(i18n.t("Размер"), i18n.t("Насколько крупно персонаж стоит на столе."),
                                     float(store.get("companion", "scale", 1.0)) * 100, 60, 150)
    look.add(scale_row)

    opacity_row, opacity, _ = slider_row(i18n.t("Непрозрачность"), i18n.t("Полупрозрачная фигура меньше отвлекает."),
                                         float(store.get("companion", "opacity", 1.0)) * 100, 30, 100)
    look.add(opacity_row)

    top_row, on_top = toggle_row(i18n.t("Поверх всех окон"), i18n.t("Персонаж не прячется за другими программами."),
                                 bool(store.get("companion", "always_on_top", True)))
    look.add(top_row)

    through_row, click_through = toggle_row(i18n.t("Не перехватывать мышь"),
                                            i18n.t("Клики проходят сквозь панель к окнам под ней."),
                                            bool(store.get("companion", "click_through", False)))
    look.add(through_row)

    life = Card(i18n.t("Живость"), i18n.t("Из чего складывается ощущение живого существа."))
    idle_row, idle = toggle_row(i18n.t("Дыхание и микродвижения"), i18n.t("Покачивание корпуса, моргание, качание волос."),
                                bool(store.get("companion", "idle_motion", True)))
    life.add(idle_row)

    follow_row, follow = toggle_row(i18n.t("Следить за курсором"), i18n.t("Взгляд и голова поворачиваются за мышью."),
                                    bool(store.get("companion", "follow_cursor", True)))
    life.add(follow_row)

    lip_row, lip = toggle_row(i18n.t("Синхронизация рта"), i18n.t("Рот открывается по громкости собственной речи."),
                              bool(store.get("companion", "lip_sync", True)))
    life.add(lip_row)

    subs_row, subs = toggle_row(i18n.t("Реплики облаком"), i18n.t("Показывать сказанное над персонажем."),
                                bool(store.get("companion", "subtitles", True)))
    life.add(subs_row)

    talk_row, talk = toggle_row(
        i18n.t("Заговаривает сама"),
        i18n.t(
            "После долгой тишины изредка подаёт голос: «Ты ещё здесь?». "
            "Никогда — пока Юки слушает, думает или отвечает."
        ),
        bool(store.get("companion", "idle_talk", True)),
    )
    life.add(talk_row)

    quiet_row, quiet, _ = slider_row(
        i18n.t("Молчание до реплики, мин"), i18n.t("Сколько тишины должно пройти, прежде чем она заговорит."),
        float(store.get("companion", "idle_talk_minutes", 15)), 5, 60,
    )
    life.add(quiet_row)

    # ---- связи: любое изменение уходит и в конфигурацию, и в живую панель
    def push(key: str, value: object) -> None:
        store.set("companion", key, value)
        actions.companion_updated()

    enabled.toggled.connect(lambda value: (push("enabled", value), actions.toggle_companion(value)))
    if model is not None:
        def choose_model() -> None:
            key = str(model.currentData())
            push("character", key)
            card = next((item for item in roster if str(item.get("id")) == key), {})
            # у персонажа есть свой голос по умолчанию — подставляем его сразу
            preferred = str(card.get("voice", "") or "")
            if preferred and preferred != str(store.get("companion", "voice", "")):
                index = voice.findData(preferred)
                if index >= 0:
                    voice.setCurrentIndex(index)

        model.currentIndexChanged.connect(choose_model)
    framing.currentIndexChanged.connect(lambda: push("framing", framing.currentData()))
    quality.currentIndexChanged.connect(lambda: push("quality", quality.currentData()))
    voice.currentIndexChanged.connect(
        lambda: (push("voice", voice.currentData()),
                 actions.apply_voice(str(voice.currentData())))
    )
    scale.valueChanged.connect(lambda value: push("scale", round(value / 100.0, 2)))
    opacity.valueChanged.connect(lambda value: push("opacity", round(value / 100.0, 2)))
    on_top.toggled.connect(lambda value: push("always_on_top", value))
    click_through.toggled.connect(lambda value: push("click_through", value))
    idle.toggled.connect(lambda value: push("idle_motion", value))
    follow.toggled.connect(lambda value: push("follow_cursor", value))
    lip.toggled.connect(lambda value: push("lip_sync", value))
    subs.toggled.connect(lambda value: push("subtitles", value))
    talk.toggled.connect(lambda value: push("idle_talk", value))
    quiet.valueChanged.connect(lambda value: push("idle_talk_minutes", int(value)))

    return _page(main, look, life)


# ---------------------------------------------------------------- аккаунт


def account_page(store: SettingsStore, actions: Actions) -> QWidget:
    card = Card(i18n.t("Оператор"), i18n.t("Как Юки обращается к вам."))
    name_row, name = input_row(i18n.t("Имя"), i18n.t("Используется в приветствиях и напоминаниях."),
                               str(store.get("account", "name", "Оператор")), i18n.t("Оператор"))
    name.editingFinished.connect(lambda: store.set("account", "name", name.text().strip()))
    card.add(name_row)

    handle_row, handle = input_row(i18n.t("Ник"), i18n.t("Необязательно — пригодится для будущей синхронизации."),
                                   str(store.get("account", "handle", "")), "@nickname")
    handle.editingFinished.connect(lambda: store.set("account", "handle", handle.text().strip()))
    card.add(handle_row)

    city_row, city = input_row(i18n.t("Город"), i18n.t("Для погоды, если геолокация по IP ошибается."),
                               str(store.get("web", "default_city", "")), "Москва")
    city.editingFinished.connect(lambda: store.set("web", "default_city", city.text().strip()))
    card.add(city_row)

    scope_row, scope = select_row(i18n.t("Где искать файлы"), i18n.t("Область поиска по диску."),
                                  [("home", i18n.t("ПАПКИ ПОЛЬЗОВАТЕЛЯ")), ("all", i18n.t("ВСЕ ДИСКИ"))],
                                  str(store.get("files", "search_scope", "home")))
    scope.currentIndexChanged.connect(lambda: store.set("files", "search_scope", scope.currentData()))
    card.add(scope_row)

    restrict_row, restrict = toggle_row(
        i18n.t("Запереть файлы в домашней папке"),
        i18n.t("Абсолютный путь вне неё (рабочие документы, чужие папки) будет отклонён."),
        bool(store.get("files", "restrict_paths", False)),
    )
    restrict.toggled.connect(lambda value: store.set("files", "restrict_paths", value))
    card.add(restrict_row)

    system = Card(i18n.t("Запуск"), i18n.t("Как Юки ведёт себя при входе в Windows."))
    autostart_row, autostart = toggle_row(
        i18n.t("Запускать вместе с Windows"),
        i18n.t("Компаньон появляется на рабочем столе сразу после входа в систему."),
        autostart_mod.enabled(),
    )
    autostart.setEnabled(autostart_mod.supported())

    def toggle_autostart(value: bool) -> None:
        # реестр — источник правды: если запись не легла, возвращаем переключатель
        actual = autostart_mod.set_enabled(value)
        store.set("ui", "autostart", actual)
        if actual != value:
            autostart.blockSignals(True)
            autostart.setChecked(actual)
            autostart.blockSignals(False)

    autostart.toggled.connect(toggle_autostart)
    system.add(autostart_row)

    status = Card(i18n.t("Состояние системы"), i18n.t("Что сейчас запущено."))
    report = QLabel(actions.diagnostics() or i18n.t("Диагностика недоступна."))
    report.setObjectName("rowHint")
    report.setWordWrap(True)
    status.add(report)
    status.add(_buttons(_action(i18n.t("ОБНОВИТЬ"), lambda: report.setText(actions.diagnostics()), ghost=True)))

    return _page(card, system, status)
