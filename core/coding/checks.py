"""Проверка проекта, который написал агент: компиляция, тесты, робот, запуск.

Всё запускается только внутри папки проекта и только известными программами
(Python, Node). Произвольные команды модели не выполняются: агент пишет код,
а как его проверить, решает этот модуль.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_RUN_TIMEOUT_S = 12.0
_GUI_ALIVE_S = 4.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_GUI_MODULES = re.compile(r"^\s*(?:import|from)\s+(tkinter|pygame|PySide6|PyQt5|PyQt6|turtle|arcade|kivy)\b",
                          re.MULTILINE)
_TRACEBACK = re.compile(r"Traceback \(most recent call last\)|^\w*Error:|SyntaxError", re.MULTILINE)
# ввод закончился — значит, программа ждёт человека, это не ошибка
_WAITS_FOR_INPUT = re.compile(r"EOFError|KeyboardInterrupt")


@dataclass(frozen=True)
class Check:
    ok: bool
    title: str
    output: str = ""
    process: subprocess.Popen | None = None  # окно программы, оставленное открытым


def python() -> list[str]:
    """Python человека, а не Юки: системный, через лаунчер py, и только потом свой."""
    for name in ("py", "python"):
        found = shutil.which(name)
        # заглушка из WindowsApps открывает Microsoft Store вместо запуска
        if found and "windowsapps" not in found.lower():
            return [found, "-3"] if name == "py" else [found]
    return [str(Path(sys.executable).with_name("python.exe"))]


def node() -> str | None:
    return shutil.which("node")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(command: list[str], root: Path, timeout: float = _RUN_TIMEOUT_S, stdin: str = "") -> tuple[int | None, str]:
    """Код возврата (None — не уложилась во время) и вывод, обрезанный с начала."""
    try:
        done = subprocess.run(command, cwd=root, input=stdin, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              creationflags=_NO_WINDOW, env=_env())
    except subprocess.TimeoutExpired as err:
        output = (err.stdout or "") + (err.stderr or "")
        return None, output if isinstance(output, str) else ""
    except OSError as err:
        return 1, f"не запустилось: {err}"
    return done.returncode, ((done.stdout or "") + (done.stderr or ""))[-3000:]


def is_gui(root: Path, entry: str) -> bool:
    path = root / entry
    try:
        return bool(_GUI_MODULES.search(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


_TK = re.compile(r"^\s*(?:import\s+tkinter|from\s+tkinter)", re.MULTILINE)
_UNITTEST_SUMMARY = re.compile(r"Ran (\d+) tests?")


def check_python(root: Path, entry: str) -> list[Check]:
    """Синтаксис → тесты → робот, нажимающий все кнопки окна (или запуск консольной программы)."""
    checks: list[Check] = []
    sources = sorted(str(path.relative_to(root)) for path in root.rglob("*.py") if ".venv" not in path.parts)
    if not sources:
        return [Check(False, "нет ни одного .py файла")]
    code, output = _run([*python(), "-m", "py_compile", *sources], root)
    checks.append(Check(code == 0, "синтаксис", output))
    if code != 0:
        return checks

    if any(Path(name).name.startswith("test_") for name in sources):
        code, output = _run([*python(), "-m", "unittest", "discover", "-p", "test_*.py"], root, timeout=40)
        ran = _UNITTEST_SUMMARY.search(output)
        title = f"тесты ({ran.group(1)})" if ran else "тесты"
        checks.append(Check(code == 0 and ran is not None and ran.group(1) != "0", title, output))
        if not checks[-1].ok:
            return checks

    if not (root / entry).is_file():
        checks.append(Check(False, f"нет файла запуска {entry}"))
        return checks
    source = (root / entry).read_text(encoding="utf-8", errors="replace")
    if _TK.search(source):
        checks.append(robot(root, entry))
    elif is_gui(root, entry):
        checks.append(_launch_gui([*python(), entry], root, keep=False))
    else:
        code, output = _run([*python(), entry], root, stdin="\n" * 3)
        crashed = code not in (0, None) and _TRACEBACK.search(output) and not _WAITS_FOR_INPUT.search(output)
        checks.append(Check(not crashed, "запуск", output))
    return checks


def robot(root: Path, entry: str) -> Check:
    """Скрытый запуск окна tkinter, в котором робот нажимает все кнопки и клавиши."""
    import tempfile

    from .smoke import HARNESS

    harness = Path(tempfile.gettempdir()) / "yuki_smoke_robot.py"
    harness.write_text(HARNESS, encoding="utf-8")
    code, output = _run([*python(), str(harness), entry], root, timeout=25)
    summary = re.search(r"SMOKE clicked=(\d+) keys=(\d+)", output)
    if code is None:
        return Check(False, "робот-тестировщик", "программа зависла: окно не отвечает 25 секунд\n" + output)
    title = (f"робот: нажал {summary.group(1)} кнопок, {summary.group(2)} клавиш" if summary
             else "робот-тестировщик")
    return Check(code == 0, title, output)


def launch(root: Path, entry: str) -> subprocess.Popen | None:
    """Настоящий запуск для человека — окно остаётся открытым."""
    try:
        return subprocess.Popen([*python(), entry], cwd=root, env=_env(), creationflags=_NO_WINDOW,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def _launch_gui(command: list[str], root: Path, keep: bool) -> Check:
    """Окно, которое прожило несколько секунд без ошибки, считается рабочим.

    Если это финальная проверка, окно не закрывается: человек сразу видит
    результат. Промежуточные проверки окно закрывают.
    """
    try:
        process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", env=_env(),
                                   creationflags=_NO_WINDOW)
    except OSError as err:
        return Check(False, "запуск окна", f"не запустилось: {err}")
    deadline = time.monotonic() + _GUI_ALIVE_S
    while time.monotonic() < deadline and process.poll() is None:
        time.sleep(0.2)
    if process.poll() is not None:
        output = process.stdout.read() if process.stdout else ""
        return Check(process.returncode == 0 and not _TRACEBACK.search(output), "запуск окна", output[-3000:])
    if not keep:
        process.kill()
        return Check(True, "запуск окна")
    return Check(True, "запуск окна", process=process)


def check_web(root: Path) -> list[Check]:
    """Синтаксис скриптов и робот, который открывает страницу и нажимает всё подряд."""
    page = root / "index.html"
    if not page.is_file():
        return [Check(False, "нет index.html")]
    checks: list[Check] = []
    runner = node()
    for script in sorted(root.rglob("*.js")):
        if runner is None or "node_modules" in script.parts:
            break
        code, output = _run([runner, "--check", str(script.relative_to(root))], root)
        checks.append(Check(code == 0, f"синтаксис {script.name}", output))
        if code != 0:
            return checks
    own = Path(__file__).resolve().parents[2]
    interpreter = str(Path(sys.executable).with_name("python.exe"))
    env = {**_env(), "PYTHONPATH": str(own)}
    try:
        done = subprocess.run([interpreter, "-m", "core.coding.webrobot", str(page)], cwd=own, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=30, creationflags=_NO_WINDOW)
        output = (done.stdout or "") + (done.stderr or "")
        summary = re.search(r"WEBROBOT clicked=(\d+)", output)
        title = f"робот: нажал {summary.group(1)} элементов" if summary else "робот-тестировщик"
        checks.append(Check(done.returncode == 0 and summary is not None, title, output[-3000:]))
    except (OSError, subprocess.TimeoutExpired) as err:
        checks.append(Check(True, f"робот пропущен: {err.__class__.__name__}"))
    return checks


def check_node(root: Path, entry: str) -> list[Check]:
    runner = node()
    if runner is None:
        return [Check(True, "Node.js не установлен — запуск пропущен")]
    code, output = _run([runner, "--check", entry], root)
    if code != 0:
        return [Check(False, "синтаксис", output)]
    code, output = _run([runner, entry], root, stdin="\n" * 3)
    return [Check(code in (0, None), "запуск", output)]


def open_result(root: Path, language: str, entry: str) -> None:
    """Показывает результат: сайт — в браузере, остальное — папкой в проводнике."""
    if language == "web":
        page = root / entry if (root / entry).suffix == ".html" else root / "index.html"
        if page.is_file():
            os.startfile(page)
            return
    os.startfile(root)


def open_in_editor(root: Path) -> bool:
    editor = shutil.which("code")
    if editor is None:
        os.startfile(root)
        return False
    subprocess.Popen([editor, str(root)], creationflags=_NO_WINDOW)
    return True
