"""Проект агента: план, файлы на диске и всё, что нужно, чтобы их безопасно писать."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_MAX_FILES = 8
_MAX_FILE_CHARS = 60_000
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FENCE = re.compile(r"```[\w+#.-]*[ \t]*\n(?P<body>.*?)\n```", re.DOTALL)
_FILE_BLOCK = re.compile(r"FILE:\s*`?(?P<path>[^\n`]+?)`?\s*\n```[\w+#.-]*[ \t]*\n(?P<body>.*?)\n```", re.DOTALL)

KINDS = ("gui", "game", "console", "web")
_ENTRY = {"python": "main.py", "web": "index.html"}


@dataclass(frozen=True)
class FileSpec:
    path: str
    role: str


@dataclass
class Plan:
    title: str
    folder: str
    language: str              # python | web
    kind: str                  # gui | game | console | web
    entry: str
    files: list[FileSpec]
    summary: str = ""
    features: list[str] = field(default_factory=list)

    @property
    def tested(self) -> bool:
        return any(Path(spec.path).name.startswith("test_") for spec in self.files)

    @classmethod
    def parse(cls, raw: str, fallback: str) -> Plan:
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
        language = str(data.get("language") or "python").lower()
        language = "web" if language in ("html", "javascript", "js", "web", "сайт", "node") else "python"
        kind = str(data.get("kind") or "").lower()
        kind = "web" if language == "web" else (kind if kind in KINDS[:3] else "gui")
        title = str(data.get("title") or fallback).strip()[:60] or "Проект"
        folder = _BAD_NAME.sub("", str(data.get("folder") or title)).strip(" .")[:60] or "Проект"
        entry = _ENTRY[language]
        specs: list[FileSpec] = []
        for item in data.get("files") or []:
            path, role = (item.get("path"), item.get("role")) if isinstance(item, dict) else (item, "")
            path = str(path or "").strip().replace("\\", "/")
            if path and path not in {spec.path for spec in specs}:
                specs.append(FileSpec(path, str(role or "").strip()[:200]))
        plan = cls(title=title, folder=folder, language=language, kind=kind, entry=entry,
                   files=specs[:_MAX_FILES],
                   summary=str(data.get("summary") or "").strip()[:400],
                   features=[str(item).strip() for item in data.get("features") or [] if str(item).strip()][:10])
        plan.normalize()
        return plan

    def normalize(self) -> None:
        """Архитектура, которую агент держит всегда, что бы ни предложила модель.

        Python: логика отдельно от окна (её можно проверить тестами), тесты на
        стандартном unittest, файл запуска — последним, когда всё, что он
        импортирует, уже написано. Сайт: разметка, стили, скрипт.
        """
        names = {spec.path for spec in self.files}
        if self.language == "python":
            if "logic.py" not in names and not any(name not in (self.entry,) and not name.startswith("test_")
                                                   and name.endswith(".py") for name in names):
                self.files.insert(0, FileSpec("logic.py", "вся логика без интерфейса: чистые функции и классы"))
            logic = next(spec.path for spec in self.files if spec.path.endswith(".py")
                         and spec.path != self.entry and not Path(spec.path).name.startswith("test_"))
            if not any(Path(spec.path).name.startswith("test_") for spec in self.files):
                self.files.append(FileSpec(f"test_{Path(logic).stem}.py",
                                           f"тесты unittest для {logic}: обычные случаи и крайние"))
            if self.entry not in names:
                self.files.append(FileSpec(self.entry, "запуск и интерфейс"))
            # порядок: логика → тесты → остальное → файл запуска
            self.files = ([spec for spec in self.files if spec.path == logic]
                          + [spec for spec in self.files if Path(spec.path).name.startswith("test_")]
                          + [spec for spec in self.files if spec.path not in (logic, self.entry)
                             and not Path(spec.path).name.startswith("test_")]
                          + [spec for spec in self.files if spec.path == self.entry])
        else:
            for path, role in (("index.html", "разметка страницы"), ("style.css", "оформление"),
                               ("script.js", "поведение страницы")):
                if path not in names:
                    self.files.append(FileSpec(path, role))
            order = {"index.html": 0, "style.css": 1, "script.js": 2}
            self.files.sort(key=lambda spec: order.get(spec.path, 3))
        self.files = [spec for spec in self.files if spec.path.lower() != "readme.md"][:_MAX_FILES]

    def as_dict(self) -> dict:
        return {"title": self.title, "summary": self.summary, "language": self.language, "kind": self.kind,
                "entry": self.entry, "features": self.features,
                "files": [{"path": spec.path, "role": spec.role} for spec in self.files]}


@dataclass
class Project:
    root: Path
    plan: Plan
    files: dict[str, str] = field(default_factory=dict)

    def write(self, files: dict[str, str]) -> list[str]:
        """Пишет файлы только внутрь папки проекта. Возвращает записанные пути."""
        written: list[str] = []
        for raw, body in files.items():
            name = str(raw).strip().replace("\\", "/")
            prefix = f"{self.root.name}/"
            if name.lower().startswith(prefix.lower()):
                name = name[len(prefix):]
            target = safe_path(self.root, name)
            if target is None or len(body) > _MAX_FILE_CHARS:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body.rstrip() + "\n", encoding="utf-8")
            relative = target.relative_to(self.root.resolve()).as_posix()
            self.files[relative] = body.rstrip() + "\n"
            written.append(relative)
        return written

    def overview(self, budget: int, full: tuple[str, ...] = ()) -> str:
        """Уже написанный код для модели в пределах бюджета знаков.

        Файлы из `full` — целиком (их агент сейчас правит или импортирует),
        остальные — оглавлением: классы, функции, константы с номерами строк.
        """
        from .edits import outline

        parts: list[str] = []
        left = budget
        for name in sorted(self.files, key=lambda item: (item not in full, item)):
            body = self.files[name]
            if name in full and len(body) <= left:
                block = f"FILE: {name}\n```\n{body}```"
            else:
                block = f"Оглавление {name} ({len(body.splitlines())} строк):\n{outline(body) or '—'}"
            if len(block) > left:
                block = block[: max(0, left)]
            parts.append(block)
            left -= len(block)
            if left <= 200:
                break
        return "\n\n".join(parts)


def safe_path(root: Path, raw: str) -> Path | None:
    """Путь внутри проекта или None, если модель пытается выйти за его пределы."""
    name = str(raw or "").strip().strip("`'\" ").replace("\\", "/").lstrip("/")
    if not name or ".." in name.split("/") or re.match(r"^[a-zA-Z]:", name):
        return None
    target = (root / name).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def parse_files(text: str) -> dict[str, str]:
    """Файлы в формате «FILE: путь» + блок кода."""
    return {match.group("path").strip(): match.group("body") for match in _FILE_BLOCK.finditer(text or "")}


def single_file(text: str) -> str:
    """Содержимое одного файла из ответа: первый блок кода, а если блока нет — весь текст."""
    match = _FENCE.search(text or "")
    if match:
        return match.group("body")
    stripped = (text or "").strip()
    return "" if stripped.startswith(("FILE:", "Вот", "Конечно")) and "\n" not in stripped else stripped


def desktop() -> Path:
    try:
        from win32com.shell import shell, shellcon

        return Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0))
    except Exception:
        return Path.home() / "Desktop"


def free_folder(parent: Path, name: str) -> Path:
    """Новая папка, не затирающая уже существующий проект: «Калькулятор 2»."""
    candidate = parent / name
    number = 2
    while candidate.exists() and any(candidate.iterdir()):
        candidate = parent / f"{name} {number}"
        number += 1
    return candidate


def readme(plan: Plan) -> str:
    """README по шаблону — без лишнего обращения к модели."""
    run = {"python": f"```\npython {plan.entry}\n```", "web": "Открой `index.html` в браузере."}[plan.language]
    tests = "\n\n## Тесты\n```\npython -m unittest\n```" if plan.tested else ""
    features = "\n".join(f"- {item}" for item in plan.features) or "- —"
    files = "\n".join(f"- `{spec.path}` — {spec.role}" for spec in plan.files)
    return (f"# {plan.title}\n\n{plan.summary}\n\n## Возможности\n{features}\n\n## Запуск\n{run}{tests}\n\n"
            f"## Файлы\n{files}\n\n---\nНаписано агентом Юки.\n")


def error_excerpt(output: str, project_files, tail: int = 12) -> str:
    """Главное из вывода ошибки: где в коде проекта она случилась и чем закончилась."""
    lines = (output or "").splitlines()
    names = tuple(Path(name).name for name in project_files)
    keep: list[str] = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("FAIL:", "ERROR:")):
            keep.append(line.strip())
        if line.lstrip().startswith("File ") and any(name in line for name in names):
            keep.append(line.strip())
            if index + 1 < len(lines):
                keep.append("    " + lines[index + 1].strip())
    keep += [line for line in lines[-tail:] if line.strip()]
    return "\n".join(dict.fromkeys(keep))[-2000:]
