"""Недавние проекты агента: список во вкладке и «доработай калькулятор» после перезапуска."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import config
from .project import FileSpec, Plan, Project

PATH = config.ROOT / "data" / "projects.json"
_KEEP = 20
_SOURCES = (".py", ".html", ".css", ".js", ".json", ".md", ".txt")


def recent() -> list[dict]:
    try:
        items = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in items if isinstance(item, dict) and Path(str(item.get("root", ""))).is_dir()]


def remember(project: Project, ok: bool) -> None:
    items = [item for item in recent() if item.get("root") != str(project.root)]
    items.insert(0, {"title": project.plan.title, "root": str(project.root), "ok": ok, "at": time.time(),
                     "kind": project.plan.kind, "plan": project.plan.as_dict()})
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(items[:_KEEP], ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def last() -> dict | None:
    items = recent()
    return items[0] if items else None


def open_project(root: Path) -> Project:
    """Готовый проект с диска: файлы и план (из истории, а если его нет — по содержимому)."""
    files = {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8", errors="replace")
             for path in sorted(root.rglob("*"))
             if path.is_file() and path.suffix in _SOURCES and path.stat().st_size < 80_000
             and not {".venv", "node_modules", "__pycache__", ".git"} & set(path.parts)}
    saved = next((item.get("plan") for item in recent() if item.get("root") == str(root)), None)
    if saved:
        plan = Plan(title=saved.get("title") or root.name, folder=root.name, language=saved.get("language", "python"),
                    kind=saved.get("kind", "gui"), entry=saved.get("entry", "main.py"),
                    files=[FileSpec(item["path"], item.get("role", "")) for item in saved.get("files", [])],
                    summary=saved.get("summary", ""), features=list(saved.get("features", [])))
    else:
        web = "index.html" in files
        entry = "index.html" if web else next((name for name in ("main.py", "app.py") if name in files),
                                              next((name for name in files if name.endswith(".py")), "main.py"))
        source = files.get(entry, "")
        kind = "web" if web else ("game" if "Canvas" in source else "gui" if "tkinter" in source else "console")
        plan = Plan(title=root.name, folder=root.name, language="web" if web else "python", kind=kind,
                    entry=entry, files=[FileSpec(name, "") for name in files if name != "README.md"])
    return Project(root=root, plan=plan, files=files)
