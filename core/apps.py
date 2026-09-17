"""Поиск и запуск приложений: меню «Пуск», реестр App Paths, игры Steam, процессы.

Именно этот модуль отвечает за «открой телеграм» и «запусти кс2» — имена берутся
из реальных ярлыков системы, а не из захардкоженного списка.
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
import threading
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

import psutil

# процессы, которые нельзя закрывать — система станет нестабильной
PROTECTED = frozenset(
    {
        "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
        "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe",
        "ctfmon.exe", "audiodg.exe", "python.exe", "pythonw.exe",
    }
)

# встроенные апплеты, у которых нет ярлыка в «Пуске»
BUILTIN: dict[str, tuple[str, ...]] = {
    "блокнот": ("notepad.exe",),
    "notepad": ("notepad.exe",),
    "калькулятор": ("calc.exe",),
    "calculator": ("calc.exe",),
    "проводник": ("explorer.exe",),
    "explorer": ("explorer.exe",),
    "терминал": ("wt.exe",),
    "командная строка": ("cmd.exe",),
    "диспетчер задач": ("taskmgr.exe",),
    "параметры": ("cmd", "/c", "start", "", "ms-settings:"),
    "настройки": ("cmd", "/c", "start", "", "ms-settings:"),
    "paint": ("mspaint.exe",),
    "пейнт": ("mspaint.exe",),
    "ножницы": ("snippingtool.exe",),
    "панель управления": ("control.exe",),
}

# как произносят названия по-русски → как они записаны в системе
ALIASES: dict[str, str] = {
    "кс": "counter-strike", "кс2": "counter-strike 2", "ксго": "counter-strike",
    "дота": "dota", "дота2": "dota 2", "гта": "gta", "майнкрафт": "minecraft",
    "валорант": "valorant", "фортнайт": "fortnite", "апекс": "apex", "пубг": "pubg",
    "тг": "telegram", "телега": "telegram", "телеграмм": "telegram",
    "вк": "vk", "хром": "chrome", "гугл хром": "chrome", "фаерфокс": "firefox",
    "эдж": "edge", "стим": "steam", "дискорд": "discord", "спотифай": "spotify",
    "ворд": "word", "эксель": "excel", "поверпоинт": "powerpoint",
    "фотошоп": "photoshop", "вс код": "visual studio code", "вскод": "code",
    "обс": "obs", "яндекс браузер": "yandex", "опера": "opera",
    "телеграм": "telegram", "телегу": "telegram", "телеге": "telegram", "телеграмма": "telegram",
    "вотсап": "whatsapp", "ватсап": "whatsapp", "вайбер": "viber", "скайп": "skype", "зум": "zoom",
    "вконтакте": "vk", "эпик": "epic games", "эпик геймс": "epic games", "роблокс": "roblox",
    "блендер": "blender", "юнити": "unity", "фигма": "figma", "ноушн": "notion",
    "обсидиан": "obsidian", "капкут": "capcut", "кап кут": "capcut", "пайчарм": "pycharm",
    "вижуал студио": "visual studio", "клод": "claude", "торрент": "torrent",
    "аймп": "aimp", "винамп": "winamp", "влс": "vlc", "майнкрафт лаунчер": "minecraft launcher",
    "тлаунчер": "tlauncher", "ворд пад": "wordpad", "эксплорер": "explorer",
}

# Ярлыки, которые не программы: инструкции, деинсталляторы, справка. Нечёткий
# поиск охотно цеплялся за них — «открой вк» запускал ярлык «Установка Gemini
# на ПК — инструкция».
_NOT_AN_APP = re.compile(
    r"инструкц|удалить|удаление|uninstall|readme|справк|документац|license|лицензи|"
    r"release notes|what's new|website|веб-сайт|сайт",
    re.IGNORECASE,
)

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    """«телеграм» → «telegram»: ярлыки в системе почти всегда на латинице."""
    return "".join(_TRANSLIT.get(char, char) for char in text.lower())


def name_variants(query: str) -> tuple[str, ...]:
    """Варианты написания, по которым имеет смысл искать приложение."""
    base = query.strip().lower().removesuffix(".exe")
    variants = [base]
    alias = ALIASES.get(base)
    if alias:
        variants.append(alias)
    latin = transliterate(base)
    if latin != base:
        variants.append(latin)
        alias_latin = ALIASES.get(latin)
        if alias_latin:
            variants.append(alias_latin)
    return tuple(dict.fromkeys(v for v in variants if v))


_CACHE_TTL_S = 300.0
_lock = threading.Lock()
_index: dict[str, Path] = {}
_index_at = 0.0
_steam: dict[str, str] = {}
_steam_at = 0.0
_uwp: dict[str, str] = {}
_uwp_at = 0.0


class AppError(RuntimeError):
    """Приложение не найдено или не запускается."""


def warm_index() -> None:
    """Собирает все индексы заранее, в фоне.

    Первый «открой стим» иначе платит за обход меню «Пуск», чтение манифестов
    Steam и вызов PowerShell разом — около пяти секунд ожидания ровно там, где
    человек ждёт мгновенной реакции. К моменту первой команды всё уже готово.
    """
    for build in (shortcut_index, steam_games, uwp_apps, app_paths):
        try:
            build()
        except Exception:  # noqa: BLE001 — один недоступный источник не мешает остальным
            continue


@dataclass(frozen=True)
class Launchable:
    name: str
    kind: str  # builtin | shortcut | exe | steam | uwp
    target: str
    argv: tuple[str, ...] = ()


# ---------------------------------------------------------------- индексы


def _start_menu_dirs() -> tuple[Path, ...]:
    roots = (
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", "")) / "Desktop",
    )
    return tuple(root for root in roots if root.exists())


def shortcut_index(force: bool = False) -> dict[str, Path]:
    """Имя в нижнем регистре → путь к ярлыку. Кэшируется на пять минут."""
    global _index, _index_at
    with _lock:
        if not force and _index and (time.monotonic() - _index_at) < _CACHE_TTL_S:
            return _index

        found: dict[str, Path] = {}
        for root in _start_menu_dirs():
            for path in root.rglob("*"):
                if path.suffix.lower() not in (".lnk", ".url"):
                    continue
                key = path.stem.lower()
                found.setdefault(key, path)
        _index, _index_at = found, time.monotonic()
        return _index


def app_paths() -> dict[str, str]:
    """Записи реестра App Paths: chrome.exe, telegram.exe и прочее."""
    result: dict[str, str] = {}
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    name = winreg.EnumKey(root, index)
                    try:
                        with winreg.OpenKey(root, name) as entry:
                            target = str(winreg.QueryValueEx(entry, "")[0]).strip('"')
                    except OSError:
                        continue
                    result.setdefault(Path(name).stem.lower(), target)
        except OSError:
            continue
    return result


def uwp_apps(force: bool = False) -> dict[str, str]:
    """Приложения из Microsoft Store: имя → AppUserModelID. Читается через Get-StartApps."""
    global _uwp, _uwp_at
    with _lock:
        if not force and _uwp and (time.monotonic() - _uwp_at) < _CACHE_TTL_S:
            return _uwp

        found: dict[str, str] = {}
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            for line in (result.stdout or "").splitlines():
                if "|" in line:
                    name, app_id = line.split("|", 1)
                    if name.strip() and app_id.strip():
                        found.setdefault(name.strip().lower(), app_id.strip())
        except (OSError, subprocess.SubprocessError):
            found = {}
        _uwp, _uwp_at = found, time.monotonic()
        return _uwp


def _steam_root() -> Path | None:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Valve\Steam") as key:
                for value in ("SteamPath", "InstallPath"):
                    try:
                        path = Path(str(winreg.QueryValueEx(key, value)[0]))
                    except OSError:
                        continue
                    if path.exists():
                        return path
        except OSError:
            continue
    return None


def steam_games(force: bool = False) -> dict[str, str]:
    """Название игры в нижнем регистре → appid. Читает манифесты всех библиотек Steam."""
    global _steam, _steam_at
    with _lock:
        if not force and _steam and (time.monotonic() - _steam_at) < _CACHE_TTL_S:
            return _steam

        games: dict[str, str] = {}
        root = _steam_root()
        if root is not None:
            libraries = [root / "steamapps"]
            vdf = root / "steamapps" / "libraryfolders.vdf"
            if vdf.exists():
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r'"path"\s+"([^"]+)"', text):
                    libraries.append(Path(match.group(1).replace("\\\\", "\\")) / "steamapps")

            for library in libraries:
                if not library.exists():
                    continue
                for manifest in library.glob("appmanifest_*.acf"):
                    text = manifest.read_text(encoding="utf-8", errors="ignore")
                    appid = re.search(r'"appid"\s+"(\d+)"', text)
                    name = re.search(r'"name"\s+"([^"]+)"', text)
                    if appid and name:
                        games.setdefault(name.group(1).lower(), appid.group(1))
        _steam, _steam_at = games, time.monotonic()
        return _steam


# ---------------------------------------------------------------- разрешение имени


def _word_hit(needle: str, candidate: str) -> bool:
    """Название содержит искомое как отдельное слово или его начало.

    Голое вхождение подстроки ловило мусор: «кс» внутри «экспорт», «вк» внутри
    чего угодно. Короткие имена (до трёх букв) узнаём только целым словом.
    """
    if len(needle) <= 3:
        return re.search(rf"(?<![\w]){re.escape(needle)}(?![\w])", candidate) is not None
    return re.search(rf"(?<![\w]){re.escape(needle)}", candidate) is not None


def resolve(query: str) -> Launchable:
    """Ищет, чем запустить: апплет → ярлык → игра Steam → App Paths → Store → PATH.

    Поиск идёт тремя проходами по всем источникам сразу: сначала точное имя, затем
    имя как слово внутри названия, и только в конце нечёткое сходство. Раньше
    нечёткий поиск шёл по первому варианту написания раньше точного по второму:
    русское «телеграм» успевало совпасть с похожим русским ярлыком раньше, чем
    дело доходило до латинского «telegram».
    """
    variants = name_variants(query)
    if not variants:
        raise AppError("не понял, что запускать")

    for needle in variants:
        for key, argv in BUILTIN.items():
            if needle == key or (len(needle) >= 4 and key.startswith(needle)):
                return Launchable(key, "builtin", argv[0], argv)

    shortcuts = {name: path for name, path in shortcut_index().items() if not _NOT_AN_APP.search(name)}
    sources: tuple[tuple[str, dict[str, object]], ...] = (
        ("shortcut", shortcuts),
        ("steam", steam_games()),
        ("exe", app_paths()),
        ("uwp", uwp_apps()),
    )

    def build(kind: str, name: str, value: object) -> Launchable:
        return Launchable(name, kind, str(value))

    for needle in variants:
        for kind, table in sources:
            if needle in table:
                return build(kind, needle, table[needle])
    for needle in variants:
        for kind, table in sources:
            hits = sorted((name for name in table if _word_hit(needle, name)), key=len)
            if hits:
                return build(kind, hits[0], table[hits[0]])
    for needle in variants:
        if len(needle) < 4:
            continue
        for kind, table in sources:
            match = difflib.get_close_matches(needle, tuple(table), n=1, cutoff=0.8)
            if match:
                return build(kind, match[0], table[match[0]])

    from shutil import which

    for needle in variants:
        executable = which(needle) or which(f"{needle}.exe")
        if executable:
            return Launchable(needle, "exe", executable)

    raise AppError(f"не нашёл приложение «{query}»")


def launch(query: str) -> str:
    target = resolve(query)
    if target.kind == "builtin":
        subprocess.Popen(list(target.argv), shell=False)
    elif target.kind == "steam":
        os.startfile(f"steam://rungameid/{target.target}")  # noqa: S606
    elif target.kind == "uwp":
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target.target}"], shell=False)
    else:
        os.startfile(target.target)  # noqa: S606 — путь получен из системного индекса
    return target.name


def wait_for_window(name: str, timeout_s: float = 10.0):  # noqa: ANN201 — WindowInfo | None
    """Ждёт появления окна запущенного приложения, чтобы можно было сразу печатать в него."""
    from . import windows as win

    words = [chunk for chunk in re.split(r"[\s_-]+", name.lower()) if len(chunk) > 2]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for window in win.enumerate_windows():
            haystack = f"{window.title} {window.process}".lower()
            if any(word in haystack for word in words):
                return window
        time.sleep(0.4)
    return None


def launch_and_focus(query: str, timeout_s: float = 10.0) -> str:
    """Запускает приложение и выводит его окно вперёд — следующая команда попадёт в него."""
    from . import windows as win

    name = launch(query)
    window = wait_for_window(name, timeout_s)
    if window is not None:
        try:
            win.focus(window)
        except win.WindowError:
            pass
        time.sleep(0.4)
    return name


# ---------------------------------------------------------------- процессы


def close(query: str) -> str:
    """Сначала пробуем аккуратно закрыть окно, если не вышло — завершаем процесс."""
    needle = query.strip().lower().removesuffix(".exe")
    if not needle:
        raise AppError("не понял, что закрывать")

    from . import windows as win

    try:
        window = win.find(needle)
        return win.close(window)
    except win.WindowError:
        pass

    killed: list[str] = []
    for process in psutil.process_iter(["name"]):
        name = str(process.info.get("name") or "").lower()
        if not name or name in PROTECTED:
            continue
        if needle in name.removesuffix(".exe"):
            try:
                process.terminate()
                killed.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    if not killed:
        raise AppError(f"«{query}» не запущено")
    return ", ".join(sorted(set(killed)))


def running(limit: int = 8) -> tuple[str, ...]:
    """Заметные приложения — те, у кого есть видимое окно."""
    from . import windows as win

    seen: list[str] = []
    for window in win.enumerate_windows():
        label = window.title.strip()
        if label and label not in seen:
            seen.append(label)
    return tuple(seen[:limit])
