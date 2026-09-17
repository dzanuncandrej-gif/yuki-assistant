"""Разбор просьб отправить сообщение: мессенджер, адресат и текст.

«Юки, открой телеграм и напиши контакту Владимир привет» — одна команда из трёх
частей. Если резать её по «и», контакт теряется, а «привет» уезжает в поле поиска.
Поэтому такие фразы разбираются целиком и до общего механизма цепочек.

Разбор идёт в два хода. Сначала из фразы вырезается всё служебное: название
мессенджера («в телеграме», «открой тг и»), слова вроде «контакту» и «в чат с».
Затем в остатке ищется простая форма «напиши ИМЯ ТЕКСТ». Раньше всё это пытались
поймать одной пачкой шаблонов, и любое лишнее слово ломало разбор: адресатом
становился «контакту», а в текст сообщения попадало «в телеграме».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# как называют мессенджеры вслух → ключ в core.outbox
APPS: dict[str, str] = {
    "телеграм": "telegram", "телеграмм": "telegram", "телеграме": "telegram",
    "телеграмме": "telegram", "телеграма": "telegram", "телеграмма": "telegram",
    "телеграмы": "telegram", "телеграммы": "telegram", "телегу": "telegram",
    "телега": "telegram", "телеге": "telegram", "тг": "telegram", "тгшке": "telegram",
    "telegram": "telegram",
    "вотсап": "whatsapp", "ватсап": "whatsapp", "вацап": "whatsapp", "вотсапе": "whatsapp",
    "ватсапе": "whatsapp", "whatsapp": "whatsapp",
    "дискорд": "discord", "дискорде": "discord", "дискорда": "discord", "discord": "discord",
    "слак": "slack", "слаке": "slack", "slack": "slack",
    "стим": "steam", "стиме": "steam", "steam": "steam",
}

# слова, которые никогда не бывают именем адресата
NOT_A_NAME = frozenset(
    {
        "мне", "тебе", "ему", "ей", "им", "нам", "вам", "себе", "это", "эту", "этот", "этого",
        "туда", "сюда", "там", "тут", "здесь", "всем", "все", "всё", "что", "как", "чтобы",
        "который", "которая", "какой", "какая", "когда", "где", "сколько", "почему",
        "сообщение", "сообщением", "текст", "письмо", "привет", "пока", "быстро", "пожалуйста",
        "заметку", "записку", "код", "программу", "песню", "статью", "сочинение", "эссе",
        "стих", "стихотворение", "историю", "сказку", "рецепт", "список", "план", "отзыв",
        "пост", "комментарий", "ответ", "файл", "число", "слово", "фразу", "букву", "имя",
        "погоду", "время", "анекдот", "шутку", "правду", "по", "на", "в", "с", "и", "а",
        "message", "text", "him", "her", "them", "me", "you", "hello", "hi",
    }
)

# глаголы отправки. «скажи», «передай» и «сообщи» считаются отправкой только если
# назван мессенджер или адресат есть в контактах: «скажи погоду» — вопрос, а не письмо
_SEND_STRONG = r"(?:напиши|напишите|отправь|отправить|пошли|скинь|черкни|send|write|text|message)"
_SEND_WEAK = r"(?:скажи|передай|сообщи)"
_FIND = r"(?:найди|найти|открой\s+(?:чат|переписку|диалог)\s+с|выбери|find)"

_APP_WORDS = "|".join(sorted(map(re.escape, APPS), key=len, reverse=True))

# «в телеграме», «через тг», «в телеграм» — вырезается откуда угодно из фразы
_APP_MENTION = re.compile(rf"\s*,?\s*\b(?:в|во|через|по|in|on|via)\s+(?P<app>{_APP_WORDS})\b\s*,?", re.I)
# «открой телеграм и …», «зайди в тг, …» в начале фразы
_APP_LEAD = re.compile(
    rf"^(?:(?:открой|запусти|зайди\s+в|перейди\s+в|open|launch)\s+)(?P<app>{_APP_WORDS})\b"
    r"\s*(?:,|\s+(?:и|а|потом|затем|then|and))?\s*",
    re.I,
)
# служебные слова перед именем: «контакту Владимир», «в чат с Вовой»
_ROLE_WORDS = re.compile(
    r"\b(?:контакту|контакт|пользователю|человеку|другу|подруге|собеседнику|в\s+чат(?:е)?\s+с|"
    r"в\s+чат|чату|в\s+личку|в\s+лс|по\s+имени)\s+",
    re.I,
)

# одно слово имени; второе — только с большой буквы («Владимиру Петрову»), иначе
# «Вове привет» разобралось бы как имя из двух слов и пустой текст
_NAME = r"(?P<contact>[A-Za-zА-ЯЁа-яё][\w\-]{0,24}(?:\s+(?-i:[A-ZА-ЯЁ])[\w\-]{1,24})?)"
_MSG_LEAD = re.compile(r"^(?:сообщение|сообщением|текст|письмо|message|text)\s*[:,—-]?\s*", re.I)

_SEND_FORMS: tuple[re.Pattern[str], ...] = (
    # найди Владимира и напиши (ему) привет
    re.compile(
        rf"^{_FIND}\s+{_NAME}\s*(?:,|\s+(?:и|а|потом|затем|and))?\s*"
        rf"(?P<verb>{_SEND_STRONG}|{_SEND_WEAK})(?:\s+(?:ему|ей|им))?(?:\s+(?P<message>.+))?$",
        re.I | re.S,
    ),
    # напиши (сообщение) Владимиру: привет
    re.compile(
        rf"^(?P<verb>{_SEND_STRONG}|{_SEND_WEAK})\s+(?:(?:сообщение|сообщеньку|текст|письмо|message)\s+)?"
        rf"{_NAME}(?:\s*[:,—-]\s*|\s+(?:сообщение|текст)\s+|\s+)?(?P<message>.+)?$",
        re.I | re.S,
    ),
)

# склонённое имя: «Владимиру», «Вове», «Андрею», «Наталье», «Марии»
_DATIVE_TAIL = re.compile(r"(?:у|ю|е|и|ой|ей)$", re.I)

# распространённые имена в основах — узнаём адресата, даже если распознавание
# записало его со строчной буквы
_COMMON_NAMES = frozenset(
    """александр саш алекс алексе лёш леш андре андрю антон артём артем борис вадим валер
    васил вас виктор вит влад владимир вов волод вячеслав слав гриш григори денис дим дмитри
    евгени жен егор иван ван игор илья иль кирилл кост константин макс максим миш михаил
    никит никола кол олег паш павел пётр пет роман ром руслан семён сергей серёж сереж
    станислав стас тимур фёдор федор юр юри ярослав
    алин алёна алена анастаси наст ан анн вер виктори вик дар дарь екатерин кат елен лен
    елизавет лиз ирин ир ксени ксюш лили любов люб мари маш марин надежд над натали наташ
    ольг ол полин свет светлан софи сон тан татьян юли юл
    мам пап бабушк бабк дедушк дед брат сестр тёт тет дяд""".split()
)


@dataclass(frozen=True)
class SendRequest:
    app: str
    contact: str
    message: str  # пусто — текст нужно спросить


def _stem(word: str) -> str:
    base = word.strip().lower()
    for _ in range(2):
        if len(base) > 2 and base[-1] in "аеёиоуыэюяьй":
            base = base[:-1]
    return base


def _looks_like_person(name: str, raw: str) -> bool:
    """Похоже ли слово на имя человека, а не на предмет разговора."""
    first = name.split()[0]
    if first.lower() in NOT_A_NAME or first.isdigit():
        return False
    if _stem(first) in _COMMON_NAMES:
        return True
    # с большой буквы посреди фразы распознавание пишет только имена
    position = raw.find(first)
    return first[:1].isupper() and position > 0 and bool(_DATIVE_TAIL.search(first) or len(first) > 2)


def _clean_message(text: str) -> str:
    cleaned = _MSG_LEAD.sub("", text.strip().strip(" ,"))
    cleaned = re.sub(r"^(?:ему|ей|им)\s+", "", cleaned, flags=re.I)
    # косвенная речь: «напиши маме, что я скоро буду» → «я скоро буду»
    cleaned = re.sub(r"^что\s+", "", cleaned, flags=re.I)
    cleaned = cleaned.strip(" :—-")
    if len(cleaned) > 1 and cleaned[0] in "«\"'“" and cleaned[-1] in "»\"'”":
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def _extract_app(phrase: str) -> tuple[str | None, str]:
    """Название мессенджера и фраза без него."""
    app: str | None = None
    lead = _APP_LEAD.match(phrase)
    if lead:
        app = APPS.get(lead.group("app").lower())
        phrase = phrase[lead.end():]
    mention = _APP_MENTION.search(phrase)
    if mention:
        app = app or APPS.get(mention.group("app").lower())
        phrase = (phrase[: mention.start()] + " " + phrase[mention.end():]).strip()
    return app, re.sub(r"\s+", " ", phrase).strip(" ,")


def parse_send(text: str, known_contact: Callable[[str], bool] | None = None) -> SendRequest | None:
    """Мессенджер, адресат и текст — или None, если это не просьба написать кому-то."""
    phrase = re.sub(r"\s+", " ", str(text or "")).strip(" .!?")
    if not phrase:
        return None

    app, rest = _extract_app(phrase)
    rest = _ROLE_WORDS.sub("", rest).strip()

    for pattern in _SEND_FORMS:
        match = pattern.match(rest)
        if match is None:
            continue
        contact = match.group("contact").strip(" ,.:;«»\"'")
        message = _clean_message(match.group("message") or "")
        if not contact or contact.split()[0].lower() in NOT_A_NAME:
            continue
        known = known_contact is not None and known_contact(contact)
        weak = re.fullmatch(_SEND_WEAK, match.group("verb"), re.I) is not None
        if weak and not (app or known):
            continue
        if not (app or known or _looks_like_person(contact, phrase)):
            continue
        return SendRequest(app=app or "telegram", contact=contact, message=message)
    return None


def mentions_messenger(text: str) -> str | None:
    """Ключ мессенджера, если он назван во фразе."""
    for word, key in APPS.items():
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            return key
    return None
