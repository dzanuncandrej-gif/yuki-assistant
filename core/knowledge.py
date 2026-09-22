"""База знаний персонажа: документы превращаются в векторы, по ним идёт поиск.

Своя база у каждого персонажа. Консультант компании и домашний компаньон не
должны делить память: ответ «по документам» обязан опираться только на то, что
загрузили именно в него.

Хранилище нарочно простое — один `.npz` на персонажа плюс JSON с текстами. Для
десятка тысяч кусков косинусная близость на numpy считается за миллисекунды, и
тащить ради этого отдельную базу данных незачем: лишняя служба, которую надо
поднимать, обновлять и чинить.

Главное правило поиска: **если подходящего куска нет, лучше вернуть пусто.**
Консультант, которому нечего процитировать, должен сказать «не знаю», а не
пересказывать самый похожий по словам абзац.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

from . import config

STORE = config.ROOT / "data" / "knowledge"

# Модель эмбеддингов. Многоязычная: документы и вопросы идут по-русски, а модели
# на одном английском заметно хуже сводят русский вопрос с русским абзацем.
EMBED_MODEL = "bge-m3"
EMBED_BATCH = 16
# Модель эмбеддингов остаётся в памяти видеокарты.
#
# Она весит около гигабайта, языковая — около четырёх с половиной, вместе они
# укладываются в восемь. Выгружать её после каждого вопроса, как делалось раньше,
# означало платить несколько секунд за перезагрузку на каждом обращении
# посетителя — при том, что место для неё есть.
EMBED_KEEP_ALIVE = "30m"

# Ниже этого сходства кусок считается не относящимся к вопросу.
#
# Порог намеренно невысокий. Разговорные формулировки — «что по деньгам»,
# «почём» — по смыслу те же, что «какая стоимость», но косинус у них ниже, и на
# 0.45 они отсекались. Второй рубеж всё равно есть: если найденные выдержки не
# отвечают на вопрос, языковая модель обязана сказать «в моих материалах об этом
# ничего нет». Пропустить лишний абзац дешевле, чем промолчать на живой вопрос.
MIN_SCORE = 0.38
TOP_K = 5

Progress = Callable[[float, str], None]  # (доля 0..1, что сейчас делается)


class KnowledgeError(RuntimeError):
    """База знаний недоступна или модель эмбеддингов не отвечает."""


@dataclass(frozen=True)
class Passage:
    """Найденный фрагмент вместе с оценкой близости и ссылкой на источник."""

    text: str
    citation: str
    score: float


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def embed(texts: Sequence[str], url: str, timeout_s: float = 180.0) -> np.ndarray:
    """Векторы для списка текстов. Нормализованные — чтобы косинус был скалярным."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    try:
        response = _session().post(
            f"{url}/api/embed",
            json={"model": EMBED_MODEL, "input": list(texts), "keep_alive": EMBED_KEEP_ALIVE},
            timeout=timeout_s,
        )
        response.raise_for_status()
        rows = response.json().get("embeddings") or []
    except (requests.RequestException, ValueError) as err:
        raise KnowledgeError(
            f"модель эмбеддингов не ответила ({EMBED_MODEL}). "
            f"Проверь: ollama pull {EMBED_MODEL}"
        ) from err
    if not rows:
        raise KnowledgeError("модель эмбеддингов вернула пусто")
    matrix = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@dataclass
class Base:
    """Загруженная база знаний одного персонажа."""

    character: str
    vectors: np.ndarray
    texts: list[str]
    citations: list[str]
    sources: list[str]
    built_at: str = ""

    @property
    def size(self) -> int:
        return len(self.texts)

    @property
    def documents(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.sources))


_lock = threading.Lock()
_cache: dict[str, Base] = {}


def _folder(character: str) -> Path:
    safe = re.sub(r"[^\w\-]+", "_", character or "default").lower()
    return STORE / safe


def exists(character: str) -> bool:
    return (_folder(character) / "index.npz").exists()


def load(character: str) -> Base | None:
    """Читает базу с диска. Держится в памяти — файл читается один раз."""
    with _lock:
        hit = _cache.get(character)
        if hit is not None:
            return hit

    folder = _folder(character)
    index, meta = folder / "index.npz", folder / "chunks.json"
    if not index.exists() or not meta.exists():
        return None
    try:
        vectors = np.load(index)["vectors"].astype(np.float32)
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except Exception as err:
        raise KnowledgeError(f"база знаний повреждена: {str(err)[:120]}") from err

    base = Base(
        character=character,
        vectors=vectors,
        texts=list(payload.get("texts", [])),
        citations=list(payload.get("citations", [])),
        sources=list(payload.get("sources", [])),
        built_at=str(payload.get("built_at", "")),
    )
    if base.size != len(vectors):
        raise KnowledgeError("индекс и тексты разошлись — пересобери базу знаний")
    with _lock:
        _cache[character] = base
    return base


def forget(character: str) -> None:
    with _lock:
        _cache.pop(character, None)


def build(character: str, paths: list[Path], url: str,
          on_progress: Progress | None = None) -> Base:
    """Собирает базу знаний из файлов. Долго и намеренно: спешить тут нельзя.

    Прогресс сообщается долей от нуля до единицы — чтением занята примерно пятая
    часть времени, остальное считает векторы.
    """
    from . import documents

    def report(done: float, what: str) -> None:
        if on_progress is not None:
            on_progress(max(0.0, min(1.0, done)), what)

    files = documents.collect(paths)
    if not files:
        raise KnowledgeError("нечего загружать: подходящих файлов не нашлось")

    report(0.0, f"нашла файлов: {len(files)}")
    chunks: list[documents.Chunk] = []
    problems: list[str] = []
    for number, path in enumerate(files, start=1):
        report(0.18 * number / len(files), f"читаю {path.name}")
        try:
            chunks.extend(documents.read(path))
        except documents.DocumentError as err:
            problems.append(str(err))
        except Exception as err:
            problems.append(f"«{path.name}»: {str(err)[:90]}")

    if not chunks:
        raise KnowledgeError("текст не извлёкся ни из одного файла. " + "; ".join(problems[:3]))

    texts = [chunk.text for chunk in chunks]
    vectors: list[np.ndarray] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]
        vectors.append(embed(batch, url))
        done = 0.18 + 0.8 * (start + len(batch)) / len(texts)
        report(done, f"разбираю фрагмент {start + len(batch)} из {len(texts)}")

    matrix = np.vstack(vectors).astype(np.float32)
    folder = _folder(character)
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(folder / "index.npz", vectors=matrix)
    (folder / "chunks.json").write_text(
        json.dumps(
            {
                "texts": texts,
                "citations": [chunk.citation for chunk in chunks],
                "sources": [chunk.source for chunk in chunks],
                "built_at": time.strftime("%Y-%m-%d %H:%M"),
                "problems": problems,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    forget(character)
    report(1.0, f"готово: {len(texts)} фрагментов из {len(files)} файлов")

    base = load(character)
    if base is None:
        raise KnowledgeError("база собралась, но не читается обратно")
    return base


def search(character: str, question: str, url: str, top_k: int = TOP_K,
           min_score: float = MIN_SCORE) -> tuple[Passage, ...]:
    """Фрагменты, относящиеся к вопросу. Пусто — значит ответа в базе нет.

    Пустой ответ здесь не сбой, а рабочее состояние: именно на нём держится
    честность консультанта. Похожий по словам, но не отвечающий на вопрос абзац
    хуже прямого «не знаю» — по нему модель уверенно сочинит.
    """
    base = load(character)
    if base is None or base.size == 0:
        return ()
    query = embed([question], url)
    if query.size == 0:
        return ()
    scores = base.vectors @ query[0]
    order = np.argsort(-scores)[: max(1, top_k)]
    found = [
        Passage(base.texts[i], base.citations[i], float(scores[i]))
        for i in order
        if scores[i] >= min_score
    ]
    return tuple(found)


def describe(character: str) -> str:
    """Короткая справка о базе — для интерфейса."""
    base = load(character)
    if base is None:
        return "база знаний не загружена"
    files = base.documents
    return (f"{base.size} фрагментов из {len(files)} файлов, собрана {base.built_at}. "
            f"Документы: {', '.join(files[:6])}")
