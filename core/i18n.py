"""Перевод статичных надписей интерфейса (не речи и не команд): меню, кнопки, подписи.

Не входит сюда: динамические строки состояния/отчётов (`core/commands.py`,
`desktop/menu/messages.py`, `desktop/menu/scenarios.py` — «Нашла «Х»…», «Отправлено: …» и
подобные) — перевести их все отдельная задача. Интерфейс строится один раз при
старте Юки, поэтому смена языка в меню («Язык» → «Interface») применяется после
перезапуска — как и смена модели распознавания.
"""

from __future__ import annotations

LANGUAGES = ("ru", "en")
DEFAULT = "ru"

# Ключ — русский текст ровно как он записан в коде интерфейса, значение — перевод.
_EN: dict[str, str] = {
    # --- control_menu.py: группы и разделы навигации ---
    "ДЕЙСТВИЯ": "ACTIONS",
    "✉  СООБЩЕНИЯ": "✉  MESSAGES",
    "Сообщения": "Messages",
    "Telegram, Discord и Steam: найти человека и отправить сообщение":
        "Telegram, Discord and Steam: find a person and send a message",
    "⚡  СЦЕНАРИИ": "⚡  SCENARIOS",
    "Сценарии": "Scenarios",
    "Несколько действий под одним именем — одной фразой или одним нажатием":
        "Several actions under one name — with one phrase or one click",
    "ЮКИ": "YUKI",
    "◧  ГОЛОС": "◧  VOICE",
    "Голос и слух": "Voice & hearing",
    "Тембр ассистента, микрофон, распознавание речи":
        "Assistant's timbre, microphone, speech recognition",
    "❋  ПЕРСОНАЖ": "❋  CHARACTER",
    "Персонаж": "Character",
    "Живой компаньон на рабочем столе": "A living companion on the desktop",
    "◈  ИНТЕЛЛЕКТ": "◈  INTELLECT",
    "Интеллект": "Intellect",
    "Модель, поведение, зрение и жесты": "Model, behavior, vision and gestures",
    "СИСТЕМА": "SYSTEM",
    "◨  ЯЗЫК": "◨  LANGUAGE",
    "Язык": "Language",
    "Язык интерфейса и язык, на котором вас слушают":
        "Interface language and the language you're heard in",
    "◍  АККАУНТ": "◍  ACCOUNT",
    "Аккаунт": "Account",
    "Оператор, город, область поиска, состояние системы":
        "Operator, city, search scope, system status",
    "Юки — управление": "Yuki — control",
    "ДИАЛОГ": "DIALOG",
    "◆  ДИАЛОГ": "◆  DIALOG",
    "Диалог": "Dialog",
    "Переписка с Юки, микрофон и уровень голоса":
        "Conversation with Yuki, microphone and voice level",
    "ESC — закрыть\nCTRL+ALT+J — окно Юки": "ESC — close\nCTRL+ALT+J — Yuki window",

    # --- pages.py: голос ---
    "Голос ассистента": "Assistant voice",
    "Тембр, которым Юки говорит вслух.": "The timbre Yuki speaks aloud with.",
    "Профиль голоса": "Voice profile",
    "Silero держит все голоса в одной модели — переключение мгновенное.":
        "Silero keeps all voices in one model — switching is instant.",
    "  (модель не скачана)": "  (model not downloaded)",
    "Движок синтеза": "Synthesis engine",
    "auto выбирает лучший доступный: Silero → Piper → Edge → системный.":
        "auto picks the best available: Silero → Piper → Edge → system.",
    "АВТОМАТИЧЕСКИ": "AUTOMATIC",
    "SILERO · офлайн": "SILERO · offline",
    "PIPER · офлайн": "PIPER · offline",
    "EDGE · сеть": "EDGE · online",
    "СИСТЕМНЫЙ": "SYSTEM",
    "Громкость речи": "Speech volume",
    "Уровень голоса относительно системного.": "Voice level relative to system volume.",
    "ПОСЛУШАТЬ": "PREVIEW",
    "ТЕСТОВАЯ ФРАЗА": "TEST PHRASE",
    "Проверка голоса. Я слышу тебя и готова помочь.":
        "Voice check. I can hear you and I'm ready to help.",
    "Слух": "Hearing",
    "Как Юки слушает микрофон.": "How Yuki listens to the microphone.",
    "Обращение по имени": "Wake word",
    "Реагировать только после слова «Юки».": "Only respond after the word “Yuki”.",
    "Нейронный детектор речи": "Neural speech detector",
    "Silero VAD вместо порога громкости — меньше ложных срабатываний.":
        "Silero VAD instead of a volume threshold — fewer false triggers.",
    "Пауза до конца фразы, мс": "Pause until end of phrase, ms",
    "Сколько тишины считать окончанием реплики.":
        "How much silence counts as the end of an utterance.",

    # --- pages.py: язык ---
    "Язык интерфейса": "Interface language",
    "На каком языке говорит меню и подписи.": "What language the menu and labels speak in.",
    "Пока доступны русский и английский.": "Russian and English are available for now.",
    "РУССКИЙ": "RUSSIAN",
    "Меню и подписи обновятся при следующем запуске Юки.":
        "The menu and labels update the next time Yuki starts.",
    "Язык распознавания": "Recognition language",
    "Что Юки ожидает услышать в микрофоне.": "What Yuki expects to hear in the microphone.",
    "Речь": "Speech",
    "Автоматический режим медленнее, но понимает обе речи.":
        "Automatic mode is slower but understands both languages.",
    "Модель распознавания": "Recognition model",
    "Крупнее модель — точнее слова, но выше задержка.":
        "A bigger model is more accurate but slower.",
    "TINY · самая быстрая": "TINY · fastest",
    "SMALL · баланс": "SMALL · balanced",
    "LARGE V3 TURBO · точная": "LARGE V3 TURBO · accurate",
    "Словарь исправлений": "Correction dictionary",
    "Подгоняет расслышанные слова под имена программ и контактов.":
        "Fits misheard words to app and contact names.",
    "Смена модели распознавания применяется при следующем запуске Юки.":
        "Changing the recognition model applies the next time Yuki starts.",

    # --- pages.py: интеллект ---
    "Модель": "Model",
    "Мозг ассистента: локальная Ollama.": "The assistant's brain: local Ollama.",
    "Основная модель": "Main model",
    "Например qwen3:8b — используется для сложных ответов.":
        "For example qwen3:8b — used for complex answers.",
    "Быстрая модель": "Fast model",
    "Отдельная лёгкая модель для болтовни. Пусто — разговор ведёт основная, и это "
    "обычно быстрее: две модели не помещаются в память видеокарты вместе и "
    "выгружают друг друга при каждом переключении.":
        "A separate lightweight model for small talk. Empty — the main model handles "
        "conversation, which is usually faster: two models don't fit in GPU memory "
        "together and evict each other on every switch.",
    "не задана": "not set",
    "Адрес Ollama": "Ollama address",
    "Где крутится сервер моделей.": "Where the model server runs.",
    "Поведение": "Behavior",
    "Насколько свободно Юки рассуждает.": "How freely Yuki reasons.",
    "Творческая свобода": "Creative freedom",
    "Ниже — строже и предсказуемее ответы.": "Lower — stricter, more predictable answers.",
    "Память диалога, реплик": "Conversation memory, turns",
    "Сколько прошлых реплик держать в контексте.": "How many past turns to keep in context.",
    "Показывать размышления": "Show reasoning",
    "Модель проговаривает ход мысли в журнале. Ответ становится в разы медленнее — "
    "включать только для отладки.":
        "The model narrates its reasoning in the log. Replies get much slower — "
        "enable only for debugging.",
    "Инициатива в звонке": "Initiative during calls",
    "Сам предлагает помощь, увидев ошибку на экране.":
        "Offers help on its own after spotting an error on screen.",
    "ОЧИСТИТЬ КОНТЕКСТ": "CLEAR CONTEXT",
    "Зрение и жесты": "Vision & gestures",
    "Камера включается вместе с режимом видеосвязи.":
        "The camera turns on together with video-call mode.",
    "Камера": "Camera",
    "Узнаёт лицо и держит взгляд персонажа.": "Recognizes faces and keeps the character's gaze on you.",
    "Управление жестами": "Gesture control",
    "Пальцы управляют музыкой, громкостью и панелью.": "Fingers control music, volume and the panel.",

    # --- pages.py: персонаж ---
    "Экранный компаньон": "Desktop companion",
    "Живой персонаж на рабочем столе: мимика, взгляд, голос.":
        "A living character on the desktop: expressions, gaze, voice.",
    "Показывать персонажа": "Show character",
    "Панель с персонажем поверх окон.": "A panel with the character on top of windows.",
    "Модель персонажа": "Character model",
    "Трёхмерная фигура со скелетом и мимикой. Стоит на рабочем столе отдельным окном.":
        "A 3D figure with a skeleton and facial expressions. Stands on the desktop as a separate window.",
    "Имя": "Name",
    "Как обращаться к персонажу.": "How to address the character.",
    "Голос персонажа": "Character voice",
    "Женские живые голоса с аниме-интонацией.": "Lively female voices with anime intonation.",
    "Внешний вид": "Appearance",
    "Размер, план и прозрачность фигуры на экране.": "Size, framing and opacity of the figure on screen.",
    "План": "Framing",
    "Насколько близко камера держит персонажа.": "How close the camera holds the character.",
    "В ПОЛНЫЙ РОСТ": "FULL BODY",
    "ПО ПОЯС": "BUST",
    "КРУПНО · ЛИЦО": "CLOSE · FACE",
    "Качество картинки": "Image quality",
    "Ниже — меньше нагрузка на видеокарту.": "Lower — less GPU load.",
    "ВЫСОКОЕ": "HIGH",
    "СРЕДНЕЕ": "MEDIUM",
    "ЛЁГКОЕ": "LOW",
    "Размер": "Size",
    "Насколько крупно персонаж стоит на столе.": "How large the character stands on the desktop.",
    "Непрозрачность": "Opacity",
    "Полупрозрачная фигура меньше отвлекает.": "A semi-transparent figure is less distracting.",
    "Поверх всех окон": "Always on top",
    "Персонаж не прячется за другими программами.": "The character doesn't hide behind other programs.",
    "Не перехватывать мышь": "Click-through",
    "Клики проходят сквозь панель к окнам под ней.": "Clicks pass through the panel to the windows beneath it.",
    "Живость": "Liveliness",
    "Из чего складывается ощущение живого существа.": "What makes it feel like a living being.",
    "Дыхание и микродвижения": "Breathing & micro-movements",
    "Покачивание корпуса, моргание, качание волос.": "Body sway, blinking, hair movement.",
    "Следить за курсором": "Follow the cursor",
    "Взгляд и голова поворачиваются за мышью.": "The gaze and head turn to follow the mouse.",
    "Синхронизация рта": "Lip sync",
    "Рот открывается по громкости собственной речи.": "The mouth opens based on the volume of its own speech.",
    "Реплики облаком": "Speech bubble",
    "Показывать сказанное над персонажем.": "Show what's said above the character.",
    "Заговаривает сама": "Speaks on its own",
    "После долгой тишины изредка подаёт голос: «Ты ещё здесь?». "
    "Никогда — пока Юки слушает, думает или отвечает.":
        "After a long silence, it occasionally speaks up: “Still there?” "
        "Never while Yuki is listening, thinking or replying.",
    "Молчание до реплики, мин": "Silence before speaking, min",
    "Сколько тишины должно пройти, прежде чем она заговорит.":
        "How much silence must pass before it speaks.",

    # --- pages.py: аккаунт ---
    "Оператор": "Operator",
    "Как Юки обращается к вам.": "How Yuki addresses you.",
    "Используется в приветствиях и напоминаниях.": "Used in greetings and reminders.",
    "Ник": "Handle",
    "Необязательно — пригодится для будущей синхронизации.": "Optional — useful for future syncing.",
    "Город": "City",
    "Для погоды, если геолокация по IP ошибается.": "For weather, if IP geolocation is wrong.",
    "Где искать файлы": "Where to search files",
    "Область поиска по диску.": "Disk search scope.",
    "ПАПКИ ПОЛЬЗОВАТЕЛЯ": "USER FOLDERS",
    "ВСЕ ДИСКИ": "ALL DRIVES",
    "Запуск": "Startup",
    "Как Юки ведёт себя при входе в Windows.": "How Yuki behaves when you sign in to Windows.",
    "Запускать вместе с Windows": "Launch with Windows",
    "Компаньон появляется на рабочем столе сразу после входа в систему.":
        "The companion appears on the desktop right after sign-in.",
    "Состояние системы": "System status",
    "Что сейчас запущено.": "What's currently running.",
    "Диагностика недоступна.": "Diagnostics unavailable.",
    "ОБНОВИТЬ": "REFRESH",
    "Запереть файлы в домашней папке": "Lock files to the home folder",
    "Абсолютный путь вне неё (рабочие документы, чужие папки) будет отклонён.":
        "An absolute path outside it (work documents, other folders) will be rejected.",

    # --- quicklaunch.py ---
    "Быстрый запуск": "Quick launch",
    "Часто нужные программы. То же самое, что сказать «открой …».":
        "Frequently needed programs. Same as saying “open …”.",
    "Добавить программу — Enter": "Add a program — Enter",
    "ДОБАВИТЬ": "ADD",
    "Убрать {name} из панели": "Remove {name} from the panel",

    # --- messages.py ---
    "Кому": "To",
    "Мессенджер и человек. Юки откроет переписку и покажет, кого нашла.":
        "Messenger and person. Yuki will open the chat and show who she found.",
    "Мессенджер": "Messenger",
    "Куда отправлять.": "Where to send.",
    "например: Максиму": "e.g.: to Max",
    "Контакт": "Contact",
    "Имя так, как вы его называете.": "The name the way you call them.",
    "Найти контакт": "Find contact",
    "Это он": "That's them",
    "Отмена": "Cancel",
    "Выберите мессенджер и введите имя.": "Choose a messenger and enter a name.",
    "Что написать": "What to say",
    "Наберите текст или продиктуйте голосом.": "Type the text or dictate it by voice.",
    "Текст сообщения…": "Message text…",
    "Продиктовать": "Dictate",
    "Отправить": "Send",

    # --- scenarios.py ---
    "Одна фраза — несколько действий. Скажите «Юки, рабочий режим» или нажмите здесь.":
        "One phrase, several actions. Say “Yuki, work mode” or click here.",
    "Выберите сценарий.": "Choose a scenario.",
    "Запустить": "Run",

    # --- theme.py: подписи состояний и ролей ---
    "ОЖИДАНИЕ": "IDLE",
    "ПРИЁМ": "LISTENING",
    "ОБРАБОТКА": "THINKING",
    "ОТВЕТ": "SPEAKING",
    "оператор": "operator",
    "юки": "yuki",
    "система": "system",
    "ошибка": "error",

    # --- widgets.py ---
    "Команда — Enter": "Command — Enter",
    "ВЫПОЛНИТЬ": "RUN",
    "МИКРОФОН ВКЛ": "MIC ON",
    "МИКРОФОН ВЫКЛ": "MIC OFF",
    "(нет файла)": "(no file)",
    "Послушать голос": "Preview voice",

    # --- window.py: главное окно, трей ---
    "Показать пульт": "Show control deck",
    "Выключить микрофон": "Mute microphone",
    "Включить микрофон": "Unmute microphone",
    "Персонаж на столе (Ctrl+J)": "Desktop character (Ctrl+J)",
    "Замолчать (Ctrl+Space)": "Silence (Ctrl+Space)",
    "Очистить контекст (Ctrl+R)": "Clear context (Ctrl+R)",
    "Выход": "Exit",
    "Голос": "Voice",
}


def _config_language() -> str:
    from . import config

    try:
        return str(config.load().get("ui", {}).get("language", DEFAULT))
    except Exception:
        return DEFAULT


_active: str | None = None


def active() -> str:
    global _active
    if _active is None:
        _active = _config_language() if _config_language() in LANGUAGES else DEFAULT
    return _active


def set_active(language: str) -> None:
    global _active
    _active = language if language in LANGUAGES else DEFAULT


def t(text: str) -> str:
    """Переводит статичную надпись, если сейчас английский интерфейс. Иначе — как есть."""
    if active() != "en":
        return text
    return _EN.get(text, text)
