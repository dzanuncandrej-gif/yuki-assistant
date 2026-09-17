"""Чтение документов: PDF, Word, PowerPoint, Excel, текст, разметка, веб-страницы.

Задача модуля одна — достать из файла осмысленный текст и разрезать его на куски,
пригодные для поиска. Куски нарезаются не по символам, а по границам абзацев и
предложений: фрагмент, оборванный на середине фразы, в ответе выглядит как мусор,
и модель по нему отвечает хуже, чем по целому абзацу.

Каждый кусок помнит, откуда он взят — файл и страница или раздел. Без этого
консультант не сможет сказать, на чём основан ответ, а проверить его будет нечем.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# Размер куска. Слишком мелкий теряет контекст («ставка 12%» без указания, чего
# именно), слишком крупный размывает поиск и раздувает запрос к модели.
CHUNK_CHARS = 900
CHUNK_OVERLAP = 150
MIN_CHUNK = 80

SUPPORTED = (".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".html", ".htm", ".rtf")

_SPACES = re.compile(r"[ \t ]+")
_BLANK = re.compile(r"\n{3,}")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class DocumentError(RuntimeError):
    """Файл не читается или формат не поддерживается."""


@dataclass(frozen=True)
class Chunk:
    """Кусок документа вместе с указанием, откуда он взят."""

    text: str
    source: str        # имя файла
    locator: str       # «стр. 4», «слайд 2», «Лист1», «раздел Введение»
    index: int = 0

    @property
    def citation(self) -> str:
        return f"{self.source} · {self.locator}" if self.locator else self.source


def _clean(text: str) -> str:
    """Убирает мусор вёрстки, не трогая структуру абзацев."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _SPACES.sub(" ", cleaned)
    # переносы слов по дефису в конце строки — частая беда PDF
    cleaned = re.sub(r"(\w)-\n(\w)", r"\1\2", cleaned)
    cleaned = _BLANK.sub("\n\n", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------- чтение форматов


def _read_pdf(path: Path) -> Iterator[tuple[str, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    empty = 0
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — одна битая страница не рушит документ
            text = ""
        if not text.strip():
            empty += 1
            continue
        yield text, f"стр. {number}"
    if empty and empty == len(reader.pages):
        raise DocumentError(
            f"«{path.name}»: в PDF нет текстового слоя — это скан. "
            "Нужен файл с текстом или распознавание."
        )


def _read_docx(path: Path) -> Iterator[tuple[str, str]]:
    import docx

    document = docx.Document(str(path))
    section = ""
    buffer: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        # заголовки становятся указателем места — по ним потом видно, откуда ответ
        if paragraph.style is not None and str(paragraph.style.name).startswith("Heading"):
            if buffer:
                yield "\n\n".join(buffer), section
                buffer = []
            section = text[:70]
            continue
        buffer.append(text)
    if buffer:
        yield "\n\n".join(buffer), section

    for number, table in enumerate(document.tables, start=1):
        rows = [
            " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            for row in table.rows
        ]
        rows = [row for row in rows if row]
        if rows:
            yield "\n".join(rows), f"таблица {number}"


def _read_pptx(path: Path) -> Iterator[tuple[str, str]]:
    from pptx import Presentation

    deck = Presentation(str(path))
    for number, slide in enumerate(deck.slides, start=1):
        pieces: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    pieces.append(text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    line = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if line:
                        pieces.append(line)
        if pieces:
            yield "\n".join(pieces), f"слайд {number}"


def _read_xlsx(path: Path) -> Iterator[tuple[str, str]]:
    import openpyxl

    book = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    for sheet in book.worksheets:
        rows: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(value).strip() for value in row if value is not None and str(value).strip()]
            if cells:
                rows.append(" | ".join(cells))
            if len(rows) >= 2000:
                break
        if rows:
            yield "\n".join(rows), f"лист {sheet.title}"
    book.close()


def _read_html(path: Path) -> Iterator[tuple[str, str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text("\n")
    if text.strip():
        yield text, ""


def _read_plain(path: Path) -> Iterator[tuple[str, str]]:
    yield path.read_text(encoding="utf-8", errors="ignore"), ""


_READERS = {
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".pptx": _read_pptx,
    ".xlsx": _read_xlsx,
    ".html": _read_html,
    ".htm": _read_html,
    ".txt": _read_plain,
    ".md": _read_plain,
    ".csv": _read_plain,
    ".rtf": _read_plain,
}


# ---------------------------------------------------------------- нарезка


def split(text: str, source: str, locator: str, start: int = 0) -> list[Chunk]:
    """Режет текст на куски по границам абзацев и предложений.

    Перекрытие между соседними кусками нужно, чтобы ответ не терялся на стыке:
    фраза, начатая в конце одного куска и законченная в начале другого, иначе не
    находится ни по одному из них.
    """
    body = _clean(text)
    if len(body) < MIN_CHUNK:
        return []

    # сначала абзацы, слишком длинные — по предложениям
    blocks: list[str] = []
    for paragraph in body.split("\n\n"):
        piece = paragraph.strip()
        if not piece:
            continue
        if len(piece) <= CHUNK_CHARS:
            blocks.append(piece)
            continue
        current = ""
        for sentence in _SENTENCE_END.split(piece):
            if len(current) + len(sentence) + 1 > CHUNK_CHARS and current:
                blocks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current.strip():
            blocks.append(current.strip())

    chunks: list[Chunk] = []
    buffer = ""
    for block in blocks:
        candidate = f"{buffer}\n\n{block}".strip() if buffer else block
        if len(candidate) > CHUNK_CHARS and buffer:
            chunks.append(Chunk(buffer.strip(), source, locator, start + len(chunks)))
            tail = buffer[-CHUNK_OVERLAP:] if CHUNK_OVERLAP else ""
            buffer = f"{tail}\n\n{block}".strip()
        else:
            buffer = candidate
    if len(buffer.strip()) >= MIN_CHUNK:
        chunks.append(Chunk(buffer.strip(), source, locator, start + len(chunks)))
    return chunks


def read(path: Path) -> list[Chunk]:
    """Все куски одного файла. Формат определяется расширением."""
    suffix = path.suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        raise DocumentError(f"«{path.name}»: формат {suffix or '?'} не поддерживается")
    if not path.exists():
        raise DocumentError(f"файла нет: {path}")

    chunks: list[Chunk] = []
    for text, locator in reader(path):
        chunks.extend(split(text, path.name, locator, start=len(chunks)))
    if not chunks:
        raise DocumentError(f"«{path.name}»: не удалось извлечь текст")
    return chunks


def collect(paths: list[Path]) -> list[Path]:
    """Разворачивает папки в список поддерживаемых файлов."""
    found: list[Path] = []
    for item in paths:
        if item.is_dir():
            for child in sorted(item.rglob("*")):
                if child.is_file() and child.suffix.lower() in SUPPORTED:
                    found.append(child)
        elif item.is_file() and item.suffix.lower() in SUPPORTED:
            found.append(item)
    return found
