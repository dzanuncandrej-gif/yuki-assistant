"""Точечные правки кода: участок вокруг ошибки и замены «найти → заменить».

Небольшая модель плохо переписывает файл в двести строк целиком: повторяет ту
же ошибку и не влезает в окно контекста. Зато она хорошо чинит, когда видит
участок с номерами строк и отвечает короткой заменой — так работают и
взрослые агенты-программисты.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FRAME = re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+)')
_EDIT = re.compile(
    r"EDIT:\s*`?(?P<path>[^\n`]+?)`?\s*\n(?:```[\w+-]*\n)?<{5,}\s*SEARCH\s*\n(?P<search>.*?)\n={5,}\s*\n"
    r"(?P<replace>.*?)\n?>{5,}\s*REPLACE",
    re.DOTALL,
)
_OUTLINE = re.compile(r"^\s*(?:class|def|async\s+def|function)\s+\w+|^\s*[A-Z_][A-Z0-9_]+\s*=", re.MULTILINE)
_SNIPPET_RADIUS = 28


@dataclass(frozen=True)
class Edit:
    path: str
    search: str
    replace: str


def failing_line(output: str, names: tuple[str, ...]) -> tuple[str, int] | None:
    """Последняя строка traceback, указывающая в файлы проекта: (имя файла, номер строки)."""
    found = None
    for match in _FRAME.finditer(output or ""):
        path = match.group("path").replace("\\", "/")
        name = next((item for item in names if path.endswith("/" + item) or path == item), None)
        if name is not None:
            found = (name, int(match.group("line")))
    if found is None:
        # SyntaxError из py_compile: «File "main.py", line 12» без полного пути уже покрыт выше,
        # а «main.py:12:» встречается у node --check
        for name in names:
            hit = re.search(re.escape(name) + r":(\d+)", output or "")
            if hit:
                found = (name, int(hit.group(1)))
    return found


def snippet(body: str, line: int, radius: int = _SNIPPET_RADIUS) -> str:
    """Участок файла с номерами строк; строка ошибки помечена стрелкой."""
    lines = body.splitlines()
    start, end = max(1, line - radius), min(len(lines), line + radius)
    marked = [f"{'>>' if number == line else '  '}{number:4d}| {lines[number - 1]}"
              for number in range(start, end + 1)]
    return "\n".join(marked)


def outline(body: str) -> str:
    """Оглавление файла: классы, функции и константы с номерами строк."""
    rows = []
    for index, text in enumerate(body.splitlines(), start=1):
        if _OUTLINE.match(text):
            rows.append(f"{index:4d}| {text.rstrip()}")
    return "\n".join(rows[:60])


def parse_edits(text: str) -> list[Edit]:
    return [Edit(match.group("path").strip(), match.group("search"), match.group("replace"))
            for match in _EDIT.finditer(text or "")]


def _strip_numbers(block: str) -> str:
    """Модель иногда копирует участок вместе с номерами «  42| » — убираем их."""
    return re.sub(r"^(?:>>| {2})?\s*\d+\|\s?", "", block, flags=re.MULTILINE)


def apply(body: str, edit: Edit) -> str | None:
    """Применяет замену. Сначала точное совпадение, потом без учёта отступов. None — не нашлось."""
    search = _strip_numbers(edit.search)
    replace = _strip_numbers(edit.replace)
    if search and search in body:
        return body.replace(search, replace, 1)
    wanted = [line.strip() for line in search.splitlines() if line.strip()]
    if not wanted:
        return None
    lines = body.splitlines()
    for start in range(len(lines)):
        window, index = [], start
        while index < len(lines) and len(window) < len(wanted):
            if lines[index].strip():
                window.append(lines[index].strip())
            index += 1
        if window == wanted:
            return _splice(lines, start, index, search, replace)
    return _fuzzy(lines, wanted, search, replace)


def _splice(lines: list[str], start: int, end: int, search: str, replace: str) -> str:
    """Заменяет строки start..end, перенося отступ найденного места на замену."""
    indent = re.match(r"\s*", lines[start]).group(0)
    original = re.match(r"\s*", search.splitlines()[0] if search.splitlines() else "").group(0)
    fixed = [indent + line[len(original):] if line.startswith(original) else line
             for line in replace.splitlines()]
    return "\n".join(lines[:start] + fixed + lines[end:]) + "\n"


def _fuzzy(lines: list[str], wanted: list[str], search: str, replace: str) -> str | None:
    """Модель часто переписывает искомые строки почти дословно: другая кавычка, пробел,
    комментарий. Ищем самое похожее окно той же длины; ниже 85% сходства не трогаем."""
    import difflib

    size = len(wanted)
    target = "\n".join(wanted)
    stripped = [line.strip() for line in lines]
    best, best_start = 0.0, -1
    for start in range(0, max(0, len(lines) - size) + 1):
        if not stripped[start]:
            continue
        ratio = difflib.SequenceMatcher(None, "\n".join(stripped[start:start + size]), target).ratio()
        if ratio > best:
            best, best_start = ratio, start
    if best < 0.85 or best_start < 0:
        return None
    return _splice(lines, best_start, best_start + size, search, replace)


def prune_tests(body: str, names: list[str]) -> tuple[str, list[str]]:
    """Убирает из файла тестов методы с данными именами. Возвращает файл и что удалено."""
    import ast

    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body, []
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [item for item in node.body if isinstance(item, ast.FunctionDef)]
            doomed = [item for item in methods if item.name in names]
            for item in doomed:
                start = min([item.lineno] + [deco.lineno for deco in item.decorator_list])
                spans.append((start, item.end_lineno or item.lineno, item.name))
    lines = body.splitlines()
    for start, end, _ in sorted(spans, reverse=True):
        del lines[start - 1:end]
    return "\n".join(lines) + "\n", [name for _, _, name in spans]


def numbered(body: str, limit: int = 160) -> str:
    """Начало файла с номерами строк — когда ошибка не указала конкретную строку."""
    lines = body.splitlines()[:limit]
    return "\n".join(f"  {number:4d}| {text}" for number, text in enumerate(lines, start=1))
