"""Полный доступ к файловой системе: поиск, обзор, чтение, запись, копирование, удаление.

Удаление по умолчанию идёт в корзину (обратимо). Безвозвратное стирание — только по
явной формулировке «удали навсегда».
"""

from __future__ import annotations

import ctypes
import os
import shutil
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

SEARCH_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "OneDrive")

CATEGORIES: dict[str, tuple[str, ...]] = {
    "видео": (".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"),
    "фото": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic"),
    "музыка": (".mp3", ".flac", ".wav", ".m4a", ".ogg"),
    "документы": (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".pptx", ".md"),
}
CATEGORIES["video"] = CATEGORIES["видео"]
CATEGORIES["photo"] = CATEGORIES["фото"]
CATEGORIES["photos"] = CATEGORIES["фото"]
CATEGORIES["music"] = CATEGORIES["музыка"]
CATEGORIES["documents"] = CATEGORIES["документы"]

FOLDER_ALIASES: dict[str, str] = {
    "загрузки": "Downloads", "downloads": "Downloads",
    "документы": "Documents", "documents": "Documents",
    "рабочий стол": "Desktop", "desktop": "Desktop",
    "картинки": "Pictures", "изображения": "Pictures", "фото": "Pictures", "pictures": "Pictures",
    "музыка": "Music", "music": "Music",
    "видео": "Videos", "videos": "Videos",
    "домашняя": ".", "home": ".",
}

MAX_READ_CHARS = 2000


class FileError(RuntimeError):
    """Файл или папка не найдены, либо операция запрещена."""


@dataclass(frozen=True)
class Hit:
    path: Path
    score: int


# ---------------------------------------------------------------- поиск


def _score(name: str, needle: str) -> int:
    lowered = name.lower()
    if lowered == needle:
        return 1000
    if lowered.startswith(needle):
        return 500 - len(lowered)
    return 200 - abs(len(lowered) - len(needle))


def _roots(scope: str) -> tuple[Path, ...]:
    home = Path.home()
    if scope == "all":
        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if bitmask & (1 << index):
                drives.append(Path(f"{chr(65 + index)}:\\"))
        return tuple(drives)
    return tuple(home / folder for folder in SEARCH_DIRS)


def search(
    query: str,
    category: str | None = None,
    limit: int = 8,
    time_budget_s: float = 5.0,
    scope: str = "home",
) -> tuple[Hit, ...]:
    """Поиск по имени с ограничением по времени. scope='all' — по всем дискам."""
    needle = query.strip().lower()
    extensions = CATEGORIES.get((category or "").lower(), ())
    if not needle and not extensions:
        return ()

    deadline = time.monotonic() + time_budget_s
    hits: list[Hit] = []

    for root in _roots(scope):
        if not root.exists():
            continue
        for current, dirs, names in os.walk(root, onerror=lambda _: None):
            if time.monotonic() > deadline:
                break
            dirs[:] = [
                d for d in dirs
                if not d.startswith((".", "$")) and d.lower() not in ("windows", "node_modules", "appdata")
            ][:60]
            for name in names:
                lowered = name.lower()
                if extensions and not lowered.endswith(extensions):
                    continue
                if needle and needle not in lowered:
                    continue
                hits.append(Hit(Path(current) / name, _score(name, needle)))
            if len(hits) >= limit * 6:
                break

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return tuple(hits[:limit])


def locate(name: str, scope: str = "home") -> Path:
    """Путь по имени: как есть, как папка-псевдоним, либо первый результат поиска."""
    raw = name.strip().strip('"')
    direct = Path(raw).expanduser()
    if direct.exists():
        return direct

    alias = FOLDER_ALIASES.get(raw.lower())
    if alias:
        return (Path.home() / alias).resolve()

    hits = search(raw, scope=scope)
    if hits:
        return hits[0].path
    raise FileError(f"не нашёл «{name}»")


# ---------------------------------------------------------------- обзор и чтение


def browse(target: Path, limit: int = 12) -> str:
    """Что лежит в папке — короткой сводкой для голоса."""
    if not target.exists():
        raise FileError(f"папки нет: {target}")
    if target.is_file():
        size = target.stat().st_size
        return f"{target.name} — файл, {size / 1024:.0f} килобайт"

    folders, docs = [], []
    try:
        for entry in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            (folders if entry.is_dir() else docs).append(entry.name)
    except PermissionError as err:
        raise FileError("нет доступа к этой папке") from err

    parts = [f"В папке {target.name or target}: {len(folders)} папок, {len(docs)} файлов"]
    if folders:
        parts.append("папки: " + ", ".join(folders[:limit]))
    if docs:
        parts.append("файлы: " + ", ".join(docs[:limit]))
    return ". ".join(parts)


def read_text(target: Path, limit: int = MAX_READ_CHARS) -> str:
    if not target.exists() or target.is_dir():
        raise FileError(f"это не файл: {target}")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        raise FileError(f"не смог прочитать: {err}") from err
    return content[:limit].strip() or "файл пустой"


def write_text(target: Path, content: str, append: bool = False) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not append:
        target.write_text(content, encoding="utf-8")
        return target

    existing = target.exists() and target.stat().st_size > 0
    with target.open("a", encoding="utf-8") as handle:
        if existing:
            handle.write("\n")  # дописываем с новой строки, а не встык
        handle.write(content)
    return target


# ---------------------------------------------------------------- изменение


class _SHFILEOPSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


_FO_DELETE = 0x0003
_FOF_ALLOWUNDO = 0x0040
_FOF_NOCONFIRMATION = 0x0010
_FOF_SILENT = 0x0004


def delete(target: Path, permanent: bool = False) -> str:
    """В корзину по умолчанию; permanent=True стирает без возможности вернуть."""
    if not target.exists():
        raise FileError(f"нет такого пути: {target}")

    if permanent:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=False)
        else:
            target.unlink()
        return target.name

    operation = _SHFILEOPSTRUCT()
    operation.wFunc = _FO_DELETE
    operation.pFrom = f"{target}\0\0"
    operation.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise FileError(f"корзина отказала (код {result})")
    return target.name


def copy(source: Path, destination: Path) -> Path:
    if not source.exists():
        raise FileError(f"нет источника: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination / source.name, dirs_exist_ok=True)
        return destination / source.name
    return Path(shutil.copy2(source, destination))


def move(source: Path, destination: Path) -> Path:
    if not source.exists():
        raise FileError(f"нет источника: {source}")
    destination.mkdir(parents=True, exist_ok=True) if destination.suffix == "" else None
    return Path(shutil.move(str(source), str(destination)))


def rename(source: Path, new_name: str) -> Path:
    if not source.exists():
        raise FileError(f"нет такого пути: {source}")
    target = source.with_name(new_name)
    source.rename(target)
    return target


def make_folder(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------- открытие


def open_path(path: Path) -> str:
    if not path.exists():
        raise FileError(f"путь не существует: {path}")
    os.startfile(str(path))  # noqa: S606 — путь пришёл из поиска или от пользователя
    return path.name


def open_folder(alias: str) -> str:
    return open_path(locate(alias))


def disks() -> str:
    """Сводка по дискам — сколько занято и свободно."""
    parts = []
    for root in _roots("all"):
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        parts.append(
            f"диск {root.drive or root}: свободно {usage.free / 1024 ** 3:.0f} "
            f"из {usage.total / 1024 ** 3:.0f} гигабайт"
        )
    return ", ".join(parts) if parts else "дисков не видно"
