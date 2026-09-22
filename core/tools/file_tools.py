"""Инструменты файловой системы: создание, чтение, поиск, перемещение, удаление, открытие.

Пути принимаются человеческие: «рабочий стол», «загрузки/отчёт.txt», абсолютный путь.
Каждое изменение проверяется на диске — модель не может отчитаться о том, чего нет.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import files
from .registry import param_bool, param_int, param_str, tool

FOLDERS = {
    "рабочий стол": "Desktop", "десктоп": "Desktop", "desktop": "Desktop",
    "документы": "Documents", "documents": "Documents",
    "загрузки": "Downloads", "downloads": "Downloads",
    "картинки": "Pictures", "изображения": "Pictures", "pictures": "Pictures",
    "музыка": "Music", "music": "Music", "видео": "Videos", "videos": "Videos",
    "домашняя папка": ".", "home": ".",
}

_scope = {"value": "home"}
_restrict = {"value": False}


def configure(scope: str, restrict_paths: bool = False) -> None:
    _scope["value"] = scope or "home"
    _restrict["value"] = bool(restrict_paths)


def _outside_home(candidate: Path) -> bool:
    home = Path.home().resolve()
    try:
        candidate.resolve().relative_to(home)
        return False
    except ValueError:
        return True


def resolve(path: str, must_exist: bool = False) -> Path:
    """«рабочий стол/отчёт.txt» → C:/Users/…/Desktop/отчёт.txt."""
    raw = str(path).strip().strip('"').replace("/", os.sep)
    if not raw:
        raise ValueError("пустой путь")

    candidate = Path(os.path.expandvars(raw)).expanduser()
    if candidate.is_absolute():
        # files.restrict_paths=true запирает файловые инструменты в домашней папке
        # пользователя — без него абсолютный путь принимался как есть, куда угодно
        # на диске, включая рабочие документы вне того, что помощник вообще искал.
        if _restrict["value"] and _outside_home(candidate):
            raise PermissionError(
                f"путь «{candidate}» вне домашней папки — files.restrict_paths запрещает "
                "выходить за её пределы. Отключи настройку, если это осознанно нужно"
            )
        if must_exist and not candidate.exists():
            raise FileNotFoundError(f"нет такого пути: {candidate}")
        return candidate

    head, _, tail = raw.partition(os.sep)
    folder = FOLDERS.get(head.strip().lower())
    if folder is not None:
        base = Path.home() if folder == "." else Path.home() / folder
        return base / tail if tail else base

    lowered = raw.lower()
    for spoken, folder_name in FOLDERS.items():
        prefix = f"{spoken} "
        if lowered.startswith(prefix):
            return Path.home() / folder_name / raw[len(prefix) :].strip()

    if must_exist:
        return files.locate(raw, scope=_scope["value"])
    return Path.home() / "Desktop" / raw


@tool(
    "create_folder",
    "Создаёт папку. Путь может быть человеческим: «рабочий стол/отчёты».",
    {"path": param_str("Куда и с каким именем создать папку")},
    ["path"],
)
def _create_folder(path: str) -> str:
    from .. import journal

    target = resolve(path)
    existed = target.exists()
    files.make_folder(target)
    if not target.is_dir():
        raise RuntimeError(f"папка не создалась: {target}")

    if not existed:
        def undo() -> str:
            if any(target.iterdir()):
                return f"папку {target.name} не трогаю — в ней уже есть файлы"
            target.rmdir()
            return f"удалил папку {target.name}"

        journal.record(f"создана папка {target}", undo=undo)
    return f"папка создана: {target}"


@tool(
    "write_file",
    "Создаёт или перезаписывает текстовый файл. Можно дописывать в конец.",
    {
        "path": param_str("Путь к файлу, например «рабочий стол/список.txt»"),
        "content": param_str("Содержимое файла"),
        "append": param_bool("true — дописать в конец, false — перезаписать"),
    },
    ["path", "content"],
    confirm=True,
)
def _write_file(path: str, content: str, append: bool = False) -> str:
    from .. import journal

    target = resolve(path)
    if not target.suffix:
        target = target.with_suffix(".txt")

    # прежнее содержимое сохраняем: перезапись файла должна быть обратимой
    backup = target.read_bytes() if target.exists() else None
    files.write_text(target, content, append=bool(append))

    def undo() -> str:
        if backup is None:
            target.unlink(missing_ok=True)
            return f"удалил созданный файл {target.name}"
        target.write_bytes(backup)
        return f"вернул прежнее содержимое {target.name}"

    journal.record(f"{'дополнил' if append else 'записал'} файл {target.name}", undo=undo)
    if not target.exists():
        raise RuntimeError(f"файл не появился: {target}")
    return f"файл {'дополнен' if append else 'записан'}: {target} ({target.stat().st_size} байт)"


@tool(
    "read_file",
    "Читает текстовый файл и возвращает его содержимое.",
    {
        "path": param_str("Путь или имя файла"),
        "limit": param_int("Сколько символов вернуть, по умолчанию 2000"),
    },
    ["path"],
)
def _read_file(path: str, limit: int = 2000) -> str:
    target = resolve(path, must_exist=True)
    return f"{target.name}: {files.read_text(target, limit=max(200, min(8000, limit)))}"


@tool(
    "list_folder",
    "Показывает содержимое папки: сколько файлов и папок, как называются.",
    {"path": param_str("Путь к папке, например «загрузки»")},
    ["path"],
)
def _list_folder(path: str) -> str:
    return files.browse(resolve(path, must_exist=True))


@tool(
    "find_files",
    "Ищет файлы и папки по имени в пользовательских каталогах.",
    {
        "query": param_str("Часть имени файла"),
        "category": param_str("Необязательно: видео, фото, музыка, документы"),
    },
    ["query"],
)
def _find_files(query: str, category: str = "") -> str:
    hits = files.search(query, category=category or None, scope=_scope["value"])
    if not hits:
        return f"ничего не найдено по запросу «{query}»"
    return "найдено: " + "; ".join(str(hit.path) for hit in hits[:6])


@tool(
    "open_path",
    "Открывает файл или папку в системе (тем приложением, которое назначено по умолчанию).",
    {"path": param_str("Путь к файлу или папке")},
    ["path"],
)
def _open_path(path: str) -> str:
    target = resolve(path, must_exist=True)
    files.open_path(target)
    return f"открыто: {target}"


@tool(
    "delete_path",
    "Удаляет файл или папку в корзину (обратимо). permanent=true стирает без возврата.",
    {
        "path": param_str("Путь к файлу или папке"),
        "permanent": param_bool("true — стереть безвозвратно"),
    },
    ["path"],
    confirm=True,
)
def _delete_path(path: str, permanent: bool = False) -> str:
    target = resolve(path, must_exist=True)
    name = files.delete(target, permanent=bool(permanent))
    if target.exists():
        raise RuntimeError(f"объект остался на месте: {target}")
    return f"удалено {'безвозвратно' if permanent else 'в корзину'}: {name}"


@tool(
    "move_path",
    "Перемещает или переименовывает файл либо папку.",
    {
        "source": param_str("Что перемещаем"),
        "destination": param_str("Куда перемещаем (папка или новый путь)"),
    },
    ["source", "destination"],
)
def _move_path(source: str, destination: str) -> str:
    from .. import journal

    src = resolve(source, must_exist=True)
    dst = resolve(destination)
    result = Path(files.move(src, dst))
    if not result.exists():
        raise RuntimeError("перемещение не подтвердилось")

    journal.record(
        f"перемещено {src.name} → {result}",
        undo=lambda: f"вернул на место: {files.move(result, src.parent)}",
    )
    return f"перемещено: {result}"


@tool(
    "copy_path",
    "Копирует файл или папку.",
    {"source": param_str("Что копируем"), "destination": param_str("Куда копируем")},
    ["source", "destination"],
)
def _copy_path(source: str, destination: str) -> str:
    result = files.copy(resolve(source, must_exist=True), resolve(destination))
    if not Path(result).exists():
        raise RuntimeError("копия не появилась")
    return f"скопировано: {result}"


@tool("disk_space", "Сколько свободного места на дисках.")
def _disks() -> str:
    return files.disks()
