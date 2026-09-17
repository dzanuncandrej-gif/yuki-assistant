"""Долгая память ассистента: факты о пользователе и его делах.

Хранится обычным JSON рядом с проектом, поэтому её видно, можно править руками и
она переживает перезапуск. В контекст модели попадают только те записи, что связаны
с текущим вопросом, — иначе память быстро съела бы всё окно контекста.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
from dataclasses import asdict, dataclass

from . import config

STORE = config.ROOT / "data" / "memory.json"
MAX_ITEMS = 400
_lock = threading.Lock()

_STOP_WORDS = frozenset(
    {"что", "как", "мой", "моя", "мои", "меня", "мне", "это", "the", "and", "для", "про", "чем"}
)


@dataclass(frozen=True)
class Fact:
    text: str
    tag: str = "общее"
    at: str = ""

    @property
    def words(self) -> set[str]:
        return _words(f"{self.text} {self.tag}")


def _words(text: str) -> set[str]:
    """Слова длиннее трёх букв, приведённые к основе — для простого поиска по смыслу."""
    raw = re.findall(r"[\w\-]+", str(text or "").lower())
    return {word[:6] for word in raw if len(word) > 3 and word not in _STOP_WORDS}


def _load() -> list[Fact]:
    if not STORE.exists():
        return []
    try:
        raw = json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = raw.get("facts", []) if isinstance(raw, dict) else raw
    result: list[Fact] = []
    for item in items:
        if isinstance(item, dict) and item.get("text"):
            result.append(Fact(str(item["text"]), str(item.get("tag", "общее")), str(item.get("at", ""))))
    return result


def _save(facts: list[Fact]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"facts": [asdict(fact) for fact in facts[-MAX_ITEMS:]]}
    STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remember(text: str, tag: str = "общее") -> Fact:
    """Запоминает факт. Похожая запись обновляется, а не дублируется."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) < 3:
        raise ValueError("слишком короткий факт")

    fact = Fact(clean, str(tag or "общее").strip().lower(), dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    with _lock:
        facts = [item for item in _load() if item.text.lower() != clean.lower()]
        facts.append(fact)
        _save(facts)
    return fact


def recall(query: str = "", limit: int = 5) -> tuple[Fact, ...]:
    """Записи, связанные с запросом. Пустой запрос — последние по времени."""
    facts = _load()
    if not facts:
        return ()
    needle = _words(query)
    if not needle:
        return tuple(facts[-limit:][::-1])

    scored = [(len(needle & fact.words), fact) for fact in facts]
    hits = [fact for score, fact in sorted(scored, key=lambda pair: -pair[0]) if score > 0]
    return tuple(hits[:limit])


def forget(query: str) -> int:
    """Удаляет записи, попавшие под запрос. Возвращает, сколько удалено."""
    needle = _words(query)
    if not needle:
        raise ValueError("нужно сказать, что забыть")
    with _lock:
        facts = _load()
        keep = [fact for fact in facts if not (needle & fact.words)]
        removed = len(facts) - len(keep)
        if removed:
            _save(keep)
    return removed


def all_facts() -> tuple[Fact, ...]:
    return tuple(_load())


def context(query: str, limit: int = 4) -> str:
    """Короткая строка для системного промпта агента."""
    hits = recall(query, limit=limit)
    if not hits:
        return ""
    return "Из памяти о пользователе: " + "; ".join(fact.text for fact in hits)
