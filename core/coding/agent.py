"""Агент-программист Юки: «напиши калькулятор и положи на рабочий стол».

Конвейер:
1. План — функции, файлы и роль каждого (без размышления: оно съедало минуты).
2. Код — по одному файлу (логика → тесты → интерфейс). Каждый файл видит
   оглавления уже написанных, поэтому имена сходятся, а окно контекста
   маленькой модели не переполняется.
3. Проверка — синтаксис, unittest, робот, который сам нажимает все кнопки
   окна или страницы.
4. Исправление — точечные замены вокруг строки ошибки, с размышлением; до
   четырёх кругов.
5. Ревью — всё ли из плана реально сделано; недостающее дописывается.
6. Результат — окно программы открыто, сайт в браузере, README в папке.

Ход работы публикуется в шину событием `coder` — его рисует вкладка «Агент».
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from .. import bus
from . import checks, edits, guides, history, prompts
from .project import Plan, Project, desktop, error_excerpt, free_folder, readme, single_file

_MAX_FIX_ROUNDS = 4
_TEST_ROUNDS = 2      # столько кругов агент спорит со своими же тестами, потом убирает несошедшиеся
_STREAM_EVERY = 0.1
_FILE_TOKENS = 2800
_CONTEXT_CHARS = 4200
_DEPENDENCY_CHARS = 9000   # тестам и окну логика нужна целиком, а не оглавлением

Generate = Callable[[str, str, int, bool], Iterable[str]]   # system, user, лимит, думать ли
AskJson = Callable[[str, str, int, bool], str]


class CoderError(RuntimeError):
    """Понятная причина, почему проект не получился."""


class _Preempted(Exception):
    """Человек заговорил с Юки — генерация агента уступает модель разговору."""


class Coder:
    """Один проект за раз; работает в своём потоке и сообщает о ходе работы в шину."""

    def __init__(self, generate: Generate, ask_json: AskJson,
                 show_result: Callable[[Path, str, str], None] | None = None,
                 busy_talking: Callable[[], bool] | None = None,
                 wait_quiet: Callable[[], None] | None = None) -> None:
        self._generate = generate
        self._ask_json = ask_json
        # Модель одна: пока агент пишет файл, вопрос человека ждал бы минуту в
        # очереди Ollama. Поэтому разговор важнее — агент прерывает свой запрос,
        # ждёт тишины и повторяет тот же шаг.
        self._busy_talking = busy_talking or (lambda: False)
        self._wait_quiet = wait_quiet or (lambda: None)
        self._show_result = show_result or _show
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.busy = False
        self.last: Project | None = None

    # ---------------------------------------------------------------- запуск

    def cancel(self) -> None:
        self._stop.set()

    def start(self, task: str, on_done: Callable[[str], None] | None = None,
              parent: Path | None = None, existing: Path | None = None) -> bool:
        """Запускает работу в фоне. False — агент уже занят другим проектом."""
        if not self._lock.acquire(blocking=False):
            return False
        self.busy = True
        self._stop.clear()

        def work() -> None:
            try:
                summary = self.build(task, parent=parent, existing=existing)
            except Exception as err:
                from ..errors import friendly

                reason = str(err) if isinstance(err, CoderError) else friendly(err)
                summary = f"Проект не получился: {reason}."
                _emit("done", text=summary, ok=False)
            finally:
                self.busy = False
                self._lock.release()
            if on_done is not None:
                on_done(summary)

        threading.Thread(target=work, name="yuki-coder", daemon=True).start()
        return True

    def build(self, task: str, parent: Path | None = None, existing: Path | None = None) -> str:
        started = time.monotonic()
        _emit("start", text=task, mode="change" if existing else "new")
        if existing is not None:
            project = history.open_project(existing)
            _emit("plan", title=project.plan.title, text=f"Дорабатываю: {task}", root=str(project.root),
                  plan=project.plan.as_dict())
            for name, body in project.files.items():
                _emit("file", path=name, content=body)
            self._change(project, task)
        else:
            project = self._new(task, parent or desktop())
        self.last = project
        ok = self._verify(project)
        if ok and existing is None and not self._stop.is_set():
            ok = self._review(project)
        seconds = int(time.monotonic() - started)
        history.remember(project, ok)
        where = f"«{project.root.name}» на рабочем столе" if project.root.parent == desktop() else str(project.root)
        if ok:
            self._show_result(project.root, project.plan.kind, project.plan.entry)
            text = (f"Готово: {project.plan.title} за {seconds // 60} мин {seconds % 60} с. "
                    f"Папка {where}, файлы: {', '.join(sorted(project.files))}.")
        else:
            text = (f"Написала {project.plan.title} в папке {where}, но довести до рабочего состояния за "
                    f"{_MAX_FIX_ROUNDS} круга не смогла — вывод ошибки во вкладке «Агент».")
        _emit("stage", stage="done", status="ok" if ok else "fail")
        _emit("done", text=text, ok=ok, root=str(project.root), seconds=seconds)
        return text

    # ---------------------------------------------------------------- новый проект

    def _new(self, task: str, parent: Path) -> Project:
        _emit("stage", stage="plan", status="run")
        _emit("step", text="Продумываю архитектуру и функции", status="run")
        raw = self._ask_json(prompts.PLAN, task, 900, False)
        try:
            plan = Plan.parse(raw, fallback=_guess_title(task))
        except (ValueError, TypeError) as err:
            raise CoderError("модель не смогла спланировать проект") from err
        root = free_folder(parent, plan.folder)
        root.mkdir(parents=True, exist_ok=True)
        project = Project(root=root, plan=plan)
        _emit("plan", title=plan.title, text=plan.summary, root=str(root), plan=plan.as_dict())
        _emit("step", text=f"План: {plan.title} — {len(plan.features)} функций, {len(plan.files)} файла",
              status="ok")
        _emit("stage", stage="plan", status="ok")

        _emit("stage", stage="code", status="run")
        for spec in plan.files:
            self._write_file(project, task, spec.path, spec.role)
        project.write({"README.md": readme(plan)})
        _emit("file", path="README.md", content=project.files["README.md"])
        _emit("stage", stage="code", status="ok")
        return project

    def _write_file(self, project: Project, task: str, path: str, role: str, error: str = "") -> None:
        plan = project.plan
        _emit("step", text=f"Пишу {path}", status="run")
        needed = _dependencies(plan, path)
        budget = _DEPENDENCY_CHARS if needed else _CONTEXT_CHARS
        context = project.overview(budget, full=needed) if project.files else "—"
        request = (f"Просьба человека: {task}\nПроект: {plan.title} — {plan.summary}\n"
                   f"Функции:\n" + "\n".join(f"- {item}" for item in plan.features) +
                   "\nФайлы проекта:\n" + "\n".join(f"- {spec.path} — {spec.role}" for spec in plan.files) +
                   f"\n\n{guides.for_file(plan.kind, path, plan.entry)}\n\nУже написано:\n{context}\n\n"
                   + (f"Прошлая версия этого файла упала с ошибкой:\n{error}\n\n" if error else "")
                   + f"Сейчас напиши файл {path} — {role}.")
        body = ""
        for _ in range(2):
            body = single_file(self._ask(prompts.FILE, request, _FILE_TOKENS, path=path))
            if body.strip():
                break
        if not body.strip():
            raise CoderError(f"модель не написала {path}")
        project.write({path: body})
        _emit("file", path=path, content=project.files[path])
        _emit("step", text=f"{path}: {len(body.splitlines())} строк", status="ok")

    # ---------------------------------------------------------------- проверка и исправление

    def _verify(self, project: Project, rounds: int = _MAX_FIX_ROUNDS) -> bool:
        _emit("stage", stage="test", status="run")
        for round_number in range(rounds + 1):
            results = self._check(project)
            failed = next((check for check in results if not check.ok), None)
            if failed is None:
                _emit("stage", stage="test", status="ok")
                return True
            if round_number == rounds or self._stop.is_set():
                break
            if failed.title.startswith("тесты") and round_number >= _TEST_ROUNDS and self._prune(project, failed):
                continue
            label = f"Исправляю ({round_number + 1}/{rounds})"
            if not self._fix(project, failed, label):
                name = _culprit(project, failed.output)
                self._write_file(project, "", name, _role(project.plan, name),
                                 error=error_excerpt(failed.output, project.files))
        _emit("stage", stage="test", status="fail")
        return False

    def _check(self, project: Project) -> list[checks.Check]:
        _emit("step", text="Проверяю: тесты и робот", status="run")
        if project.plan.language == "web":
            results = checks.check_web(project.root)
        else:
            results = checks.check_python(project.root, project.plan.entry)
        for check in results:
            _emit("check", text=check.title, ok=check.ok, output=check.output[-2500:])
        return results

    def _fix(self, project: Project, failed: checks.Check, label: str) -> bool:
        """Точечная правка по строке ошибки. False — правку не удалось применить."""
        names = tuple(Path(name).name for name in project.files)
        where = edits.failing_line(failed.output, names)
        name = next((item for item in project.files if where and Path(item).name == where[0]),
                    _culprit(project, failed.output))
        body = project.files.get(name, "")
        if not body:
            return False
        _emit("step", text=f"{label}: {name}" + (f", строка {where[1]}" if where else ""), status="run")
        related = tuple(item for item in _related(project, name) if item in project.files)
        test_failed = Path(name).name.startswith("test_")
        # упавший тест — это спор двух файлов: модель должна видеть логику целиком, а тест — узко
        snippet = (edits.snippet(body, where[1], radius=14 if test_failed else 28) if where
                   else edits.numbered(body, 160))
        hint = ("\nЭто упал тест. Сравни с планом и логикой: если логика не делает обещанного — исправь логику, "
                "если тест ждёт невозможного — исправь тест.\n" if test_failed else "")
        request = (f"Проверка «{failed.title}» не прошла:\n{error_excerpt(failed.output, project.files)}\n{hint}\n"
                   f"Участок {name}:\n{snippet}\n\nСвязанный код:\n"
                   f"{project.overview(6000 if test_failed else 3000, full=related)}")
        reply = self._ask(prompts.EDIT, request, 2600, think=True)
        applied = self._apply(project, reply, default=name)
        _emit("step", text=f"{label}: замен {applied}" if applied else f"{label}: правка не легла, переписываю",
              status="ok" if applied else "fail")
        return applied > 0

    def _prune(self, project: Project, failed: checks.Check) -> bool:
        """Тесты агент придумал сам. Если за два круга они не сошлись с рабочим кодом,
        несошедшиеся убираются, а проект проверяется дальше — роботом и запуском."""
        doomed = re.findall(r"^(?:FAIL|ERROR): (\w+) \(", failed.output, re.MULTILINE)
        tests = [name for name in project.files if Path(name).name.startswith("test_")]
        if not doomed or not tests:
            return False
        removed: list[str] = []
        for name in tests:
            body, gone = edits.prune_tests(project.files[name], doomed)
            if not gone:
                continue
            removed += gone
            if "def test_" in body:
                project.write({name: body})
                _emit("file", path=name, content=project.files[name])
            else:
                (project.root / name).unlink(missing_ok=True)
                project.files.pop(name, None)
                _emit("removed", path=name)
        if removed:
            _emit("step", text=f"Убрала несошедшиеся тесты: {', '.join(removed)}", status="ok")
        return bool(removed)

    def _apply(self, project: Project, reply: str, default: str) -> int:
        """Применяет замены и новые файлы из ответа модели. Возвращает число изменений."""
        changed: dict[str, str] = {}
        for edit in edits.parse_edits(reply):
            name = _match_name(project, edit.path) or default
            current = changed.get(name, project.files.get(name, ""))
            result = edits.apply(current, edit)
            if result is not None:
                changed[name] = result
        from .project import parse_files

        for name, body in parse_files(reply).items():
            changed[name] = body
        for name in project.write(changed):
            _emit("file", path=name, content=project.files[name])
        return len(changed)

    # ---------------------------------------------------------------- ревью и доработка

    def _review(self, project: Project) -> bool:
        """Сверка с планом: всё ли обещанное реально сделано. Недостающее дописывается один раз."""
        plan = project.plan
        if not plan.features:
            return True
        _emit("stage", stage="review", status="run")
        _emit("step", text="Ревью: сверяю код с планом", status="run")
        request = ("Функции из плана:\n" + "\n".join(f"- {item}" for item in plan.features) +
                   f"\n\nКод:\n{project.overview(9000, full=(plan.entry,))}")
        try:
            verdict = json.loads(re.search(r"\{.*\}", self._ask_json(prompts.REVIEW, request, 500, False),
                                           re.DOTALL).group(0))
        except (AttributeError, ValueError):
            _emit("stage", stage="review", status="ok")
            return True
        missing = [str(item) for item in verdict.get("missing") or [] if str(item).strip()][:4]
        _emit("review", missing=missing, notes=str(verdict.get("notes") or ""))
        if not missing:
            _emit("step", text="Ревью: все функции на месте", status="ok")
            _emit("stage", stage="review", status="ok")
            return True
        _emit("step", text=f"Ревью: дописываю {len(missing)} — " + "; ".join(missing), status="run")
        reply = self._ask(prompts.ADD, "Не хватает:\n" + "\n".join(f"- {item}" for item in missing) +
                          f"\n\nКод:\n{project.overview(8000, full=(plan.entry,))}", 3200, think=True)
        if self._apply(project, reply, default=plan.entry):
            ok = self._verify(project, rounds=2)
        else:
            ok = True  # дописать не вышло, но рабочая версия цела
        _emit("stage", stage="review", status="ok" if ok else "fail")
        return ok

    def _change(self, project: Project, task: str) -> None:
        _emit("stage", stage="code", status="run")
        _emit("step", text="Продумываю изменения", status="run")
        full = tuple(sorted(project.files, key=lambda name: len(project.files[name])))
        reply = self._ask(prompts.CHANGE, f"Просьба: {task}\n\nКод проекта:\n{project.overview(8000, full=full)}",
                          3600, think=True)
        applied = self._apply(project, reply, default=project.plan.entry)
        if not applied:
            raise CoderError("не получилось внести изменения — попробуй сформулировать иначе")
        _emit("step", text=f"Изменено файлов: {applied}", status="ok")
        _emit("stage", stage="code", status="ok")

    # ---------------------------------------------------------------- модель

    def _ask(self, system: str, user: str, limit: int, think: bool = False, path: str = "") -> str:
        import requests

        failures = 0
        while True:
            self._yield_to_talk()
            pieces = self._generate(system, user, limit, think)
            try:
                text = "".join(self._throttled(pieces, path))
                break
            except _Preempted:
                _emit("stream_reset", path=path)
                continue
            except requests.ConnectionError:
                failures += 1
                if failures >= 2:
                    raise
                # Ollama упала посреди ответа: подъём берёт на себя агент, мы повторяем запрос
                _emit("step", text="Связь с моделью оборвалась — повторяю", status="fail")
            finally:
                close = getattr(pieces, "close", None)
                if close is not None:
                    close()  # закрытый поток обрывает генерацию и в самой Ollama
        if self._stop.is_set():
            raise CoderError("остановлено")
        return text

    def _yield_to_talk(self) -> None:
        if self._busy_talking():
            _emit("step", text="Пауза: ты говоришь с Юки — продолжу, когда закончите", status="run")
            self._wait_quiet()
            _emit("step", text="Продолжаю", status="ok")

    def _throttled(self, pieces: Iterable[str], path: str) -> Iterator[str]:
        """Отдаёт текст дальше и раз в долю секунды показывает его в интерфейсе."""
        buffer: list[str] = []
        last = time.monotonic()
        for piece in pieces:
            if self._stop.is_set():
                break
            if self._busy_talking():
                raise _Preempted()
            if not piece:
                continue
            buffer.append(piece)
            yield piece
            if time.monotonic() - last >= _STREAM_EVERY:
                _emit("stream", text="".join(buffer), path=path)
                buffer.clear()
                last = time.monotonic()
        if buffer:
            _emit("stream", text="".join(buffer), path=path)


# ---------------------------------------------------------------- помощники


def _dependencies(plan: Plan, path: str) -> tuple[str, ...]:
    """Какие файлы нужны целиком, чтобы написать этот: тестам и окну — логика, стилям и скрипту — разметка."""
    if plan.language == "web":
        return ("index.html",) if path != "index.html" else ()
    logic = tuple(spec.path for spec in plan.files if spec.path.endswith(".py") and spec.path != plan.entry
                  and not Path(spec.path).name.startswith("test_"))
    return logic if path not in logic else ()


def _related(project: Project, name: str) -> tuple[str, ...]:
    plan = project.plan
    if plan.language == "web":
        return tuple(item for item in ("index.html", "script.js") if item != name)
    return _dependencies(plan, name) + ((plan.entry,) if Path(name).name.startswith("test_") else ())


def _culprit(project: Project, output: str) -> str:
    """Файл, который скорее всего виноват, если ошибка не указала строку."""
    for name in sorted(project.files, key=lambda item: -len(item)):
        if Path(name).name in (output or ""):
            return name
    return project.plan.entry


def _role(plan: Plan, path: str) -> str:
    return next((spec.role for spec in plan.files if spec.path == path), "")


def _match_name(project: Project, raw: str) -> str | None:
    name = str(raw or "").strip().strip("`").replace("\\", "/")
    if name in project.files:
        return name
    return next((item for item in project.files if Path(item).name == Path(name).name), None)


def _guess_title(task: str) -> str:
    match = re.search(r"(?:проект|программ\w*|игр\w*|сайт\w*|приложени\w*)\s+(\w+)", task, re.IGNORECASE)
    return (match.group(1) if match else "Проект").capitalize()


def _show(root: Path, kind: str, entry: str) -> None:
    """Результат человеку: окно программы, сайт в браузере, консоль — папкой."""
    if kind in ("gui", "game"):
        if checks.launch(root, entry) is not None:
            return
    checks.open_result(root, "web" if kind == "web" else "folder", entry)


def _emit(event: str, **data) -> None:
    bus.bus.publish({"type": "coder", "event": event, **data})
