"""Книга людей: как человек называет собеседника → как тот записан в мессенджере.

«Открой Диму и напиши привет» — «Дима» в Telegram может быть «Дмитрий Иванов»,
и поиск по «Диме» то находит троих, то никого. Книга решает это раз и навсегда:
одно сопоставление, после которого Юки ищет сразу по точному имени и не
переспрашивает.

Записи появляются двумя путями: вручную в меню «Сообщения» и сами — после
первой удачной отправки Юки запоминает, кого нашла по этому имени.
Хранится в `data/people.json`; старый раздел `contacts` из config.json
подхватывается как стартовый набор.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass

from . import config

PATH = config.ROOT / "data" / "people.json"
_lock = threading.Lock()
_cache: list[Person] | None = None

# имена, под которыми Telegram показывает «Избранное»
SAVED = frozenset({"избранное", "избранные", "избранном", "избранного", "saved messages", "сохранённые",
                   "сохраненные", "сохранённые сообщения", "сохраненные сообщения"})


@dataclass(frozen=True)
class Person:
    alias: str          # как его называют вслух: «дима», «папа», «избранное»
    name: str           # как он записан в мессенджере: «Дмитрий Иванов»
    app: str = "telegram"


def _stem(word: str) -> str:
    """«Диме», «Диму», «Димой» → «дим»: падеж не должен мешать узнать человека."""
    base = str(word or "").strip().lower().replace("ё", "е")
    for ending in ("ами", "ями", "ому", "ему", "ой", "ей", "ом", "ем", "ую", "юю"):
        if base.endswith(ending) and len(base) - len(ending) >= 3:
            return base[: -len(ending)]
    for _ in range(2):
        if len(base) > 3 and base[-1] in "аеёиоуыэюяьй":
            base = base[:-1]
    return base


def _key(text: str) -> str:
    return " ".join(_stem(word) for word in str(text or "").split() if word)


def _load() -> list[Person]:
    global _cache
    if _cache is not None:
        return _cache
    people: list[Person] = []
    if PATH.is_file():
        try:
            for row in json.loads(PATH.read_text(encoding="utf-8")):
                if row.get("alias") and row.get("name"):
                    people.append(Person(str(row["alias"]).lower(), str(row["name"]), str(row.get("app") or "telegram")))
        except (OSError, ValueError, AttributeError):
            people = []
    # старые сопоставления из config.json → contacts
    legacy = config.load().get("contacts") or {}
    known = {_key(person.alias) for person in people}
    for alias, name in legacy.items():
        if _key(alias) not in known:
            people.append(Person(str(alias).lower(), str(name)))
    _cache = people
    return people


def _save(people: list[Person]) -> None:
    global _cache
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps([asdict(person) for person in people], ensure_ascii=False, indent=2),
                    encoding="utf-8")
    _cache = list(people)


def everyone() -> tuple[Person, ...]:
    with _lock:
        return tuple(_load())


def lookup(spoken: str) -> Person | None:
    """Человек по тому, как его назвали, с любым падежом. Иначе None."""
    wanted = _key(spoken)
    if not wanted:
        return None
    plain = str(spoken).strip().lower().replace("ё", "е")
    if plain in SAVED or _key(plain) in {_key(item) for item in SAVED}:
        return Person("избранное", "Избранное")
    with _lock:
        for person in _load():
            if _key(person.alias) == wanted:
                return person
    return None


def remember(alias: str, name: str, app: str = "telegram") -> Person:
    """Добавляет или обновляет запись. Прежняя запись с тем же именем заменяется."""
    person = Person(str(alias).strip().lower(), str(name).strip(), app or "telegram")
    if not person.alias or not person.name:
        raise ValueError("нужно и как называешь, и как записан")
    with _lock:
        people = [item for item in _load() if _key(item.alias) != _key(person.alias)]
        people.append(person)
        _save(people)
    return person


def forget(alias: str) -> bool:
    with _lock:
        people = _load()
        kept = [item for item in people if _key(item.alias) != _key(alias)]
        if len(kept) == len(people):
            return False
        _save(kept)
        return True


def learn(spoken: str, found: str, app: str = "telegram") -> None:
    """После удачной отправки: запоминаем, кого нашли по этому имени."""
    if not spoken or not found or lookup(spoken) is not None:
        return
    clean = str(found).strip()
    # Запоминаем только подпись из списка чатов. Никнейм или заголовок окна
    # («@SmbatDS») сюда попадать не должен: по нему потом искали, Telegram
    # показывал «Папа», имена не сходились — и Юки говорила «не найден».
    if clean.lower() in SAVED or clean.startswith("@") or len(clean) > 60:
        return
    try:
        remember(_nominative(spoken), found, app)
    except (OSError, ValueError):
        pass


def _nominative(spoken: str) -> str:
    """«диме» → «дима»: в меню запись читается по-человечески."""
    word = str(spoken).strip().lower()
    for tail, repl in (("е", "а"), ("у", "а"), ("ой", "а"), ("ей", "я"), ("ю", "я")):
        if word.endswith(tail) and len(word) > 3:
            return word[: -len(tail)] + repl
    return word
