import json
from pathlib import Path

import pytest

from core import coding
from core.coding import checks, edits, history, project
from core.coding.agent import Coder

BROKEN = '''COLORS = {}


class App:
    def __init__(self):
        accent = "#58b6ff"
        self.title = "Калькулятор"

    def run(self):
        return accent


print(App().run())
'''

LOGIC = '''def add(a, b):
    """Сумма."""
    return a + b
'''

TESTS = '''import unittest

from logic import add


class TestAdd(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 2), 4)

    def test_wrong(self):
        self.assertEqual(add(2, 2), 5)


if __name__ == "__main__":
    unittest.main()
'''

PLAN = json.dumps({"title": "Калькулятор", "folder": "Калькулятор", "language": "python", "kind": "console",
                   "summary": "консольный калькулятор", "features": ["сложение"],
                   "files": [{"path": "logic.py", "role": "логика"}, {"path": "main.py", "role": "запуск"}]})


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "PATH", tmp_path / "projects.json")


def test_plan_always_has_logic_tests_and_entry_in_order():
    plan = project.Plan.parse(PLAN, "x")
    assert [spec.path for spec in plan.files] == ["logic.py", "test_logic.py", "main.py"]
    web = project.Plan.parse(json.dumps({"title": "Сайт", "language": "web", "files": []}), "x")
    assert [spec.path for spec in web.files] == ["index.html", "style.css", "script.js"]


def test_paths_cannot_escape_project(tmp_path):
    assert project.safe_path(tmp_path, "../evil.py") is None
    assert project.safe_path(tmp_path, "C:/Windows/evil.py") is None
    assert project.safe_path(tmp_path, "src/app.py") == (tmp_path / "src" / "app.py").resolve()


def test_project_folder_prefix_is_dropped(tmp_path):
    item = project.Project(root=tmp_path / "Калькулятор", plan=project.Plan.parse(PLAN, "x"))
    item.root.mkdir()
    assert item.write({"Калькулятор/main.py": "print(1)"}) == ["main.py"]


def test_single_file_reads_first_block():
    assert project.single_file("Вот файл:\n```python\nprint('привет')\n```\nи всё") == "print('привет')"


def test_existing_project_is_never_overwritten(tmp_path):
    (tmp_path / "Змейка").mkdir()
    (tmp_path / "Змейка" / "main.py").write_text("old", encoding="utf-8")
    assert project.free_folder(tmp_path, "Змейка").name == "Змейка 2"


def test_failing_line_and_snippet_point_to_project_code():
    output = ('Traceback (most recent call last):\n  File "C:\\p\\main.py", line 13, in <module>\n'
              '  File "C:\\p\\main.py", line 10, in run\nNameError: name \'accent\' is not defined')
    assert edits.failing_line(output, ("main.py",)) == ("main.py", 10)
    assert ">>  10|         return accent" in edits.snippet(BROKEN, 10)


def test_edit_applies_exact_loose_and_fuzzy():
    assert "return ACCENT" in edits.apply(BROKEN, edits.Edit("main.py", "  10|         return accent",
                                                              "        return ACCENT"))
    assert "self.accent" in edits.apply(BROKEN, edits.Edit("main.py", 'accent = "#58b6ff"',
                                                           'self.accent = "#58b6ff"'))
    # модель переврала кавычки и пробел — 85% сходства хватает
    fuzzy = edits.apply(BROKEN, edits.Edit("main.py", "accent  = '#58b6ff'", 'self.accent = "#58b6ff"'))
    assert fuzzy is not None and "self.accent" in fuzzy


def test_prune_removes_only_named_tests():
    body, gone = edits.prune_tests(TESTS, ["test_wrong"])
    assert gone == ["test_wrong"] and "def test_add" in body and "def test_wrong" not in body
    compile(body, "t", "exec")


@pytest.mark.parametrize("phrase, expected", [
    ("юки привет мне надо написать проект калькулятор создай на рабочем столе папку и напиши код", True),
    ("напиши мне игру змейка на питоне", True),
    ("сделай сайт визитку", True),
    ("напиши маме привет", False),
    ("напиши сообщение диме", False),
])
def test_wants_code(phrase, expected):
    assert coding.wants_code(phrase) is expected


@pytest.mark.parametrize("phrase, expected", [
    ("добавь в калькулятор тёмную тему", True),
    ("доработай проект: добавь звук", True),
    ("доработай", True),
    ("добавь будильник на семь утра", False),
    ("сделай громкость 30", False),
])
def test_wants_change(phrase, expected):
    assert coding.wants_change(phrase, "Калькулятор") is expected


def test_robot_catches_a_crashing_button(tmp_path):
    (tmp_path / "main.py").write_text(
        "import tkinter as tk\nroot = tk.Tk()\n"
        "tk.Button(root, text='Сломано', command=lambda: 1 / 0).pack()\n"
        "tk.Button(root, text='Хорошо', command=lambda: None).pack()\nroot.mainloop()\n", encoding="utf-8")
    result = checks.robot(tmp_path, "main.py")
    assert not result.ok and "ZeroDivisionError" in result.output
    assert "нажал 2 кнопок" in result.title


def test_build_fixes_a_failing_test_and_reviews(tmp_path):
    """Подставная модель: логика с ошибкой, правка по тесту, ревью без замечаний."""
    replies = iter([
        "```python\ndef add(a, b):\n    return a - b\n```",                       # logic.py — с ошибкой
        f"```python\n{TESTS.replace(chr(10) + '    def test_wrong(self):' + chr(10) + '        self.assertEqual(add(2, 2), 5)' + chr(10), '')}```",
        "```python\nfrom logic import add\n\nif __name__ == '__main__':\n    print(add(2, 3))\n```",
        "EDIT: logic.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE",
    ])
    calls = []

    def generate(system, user, limit, think):
        calls.append(think)
        yield next(replies)

    def ask_json(system, user, limit, think):
        return PLAN if "ведущий" in system else '{"missing": [], "notes": "ок"}'

    worker = Coder(generate, ask_json, show_result=lambda *_: None)
    summary = worker.build("напиши калькулятор", parent=tmp_path)
    assert summary.startswith("Готово"), summary
    root = tmp_path / "Калькулятор"
    assert "a + b" in (root / "logic.py").read_text(encoding="utf-8")
    assert (root / "README.md").is_file()
    assert calls == [False, False, False, True]           # думает только над исправлением
    assert history.last()["title"] == "Калькулятор"


def test_code_help_intent():
    from core import codehelp

    assert codehelp.wants_help("юки что за ошибка")
    assert codehelp.wants_help("почему у меня код не работает")
    assert not codehelp.wants_help("напиши калькулятор")
    text = "Причина.\n\n## Исправление\n```python\nself.accent = 1\n```"
    assert codehelp.first_code(text) == "self.accent = 1"


def test_open_project_infers_plan_without_history(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (tmp_path / "script.js").write_text("console.log(1)", encoding="utf-8")
    item = history.open_project(Path(tmp_path))
    assert item.plan.language == "web" and item.plan.entry == "index.html"


def test_coder_yields_the_model_to_conversation(tmp_path):
    """Пока человек говорит с Юки, агент обрывает свой запрос и повторяет его после."""
    talking = {"now": False, "waited": 0}
    attempts = []

    def generate(system, user, limit, think):
        attempts.append(1)
        yield "```python\n"
        if len(attempts) == 1:
            talking["now"] = True          # человек заговорил посреди генерации
        yield "def add(a, b):\n    return a + b\n```"

    def wait_quiet():
        talking["waited"] += 1
        talking["now"] = False

    worker = Coder(generate, lambda *a: PLAN, show_result=lambda *_: None,
                   busy_talking=lambda: talking["now"], wait_quiet=wait_quiet)
    text = worker._ask("s", "u", 100)
    assert "return a + b" in text and len(attempts) == 2 and talking["waited"] == 1
