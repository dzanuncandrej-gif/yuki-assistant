import pytest

from core import automation, replies, selection
from core import windows as win


class FakeWindow:
    hwnd = 42
    title = "Письмо"
    process = "chrome.exe"


@pytest.fixture()
def desk(monkeypatch):
    state = {"clipboard": "старое", "selected": "Привет, как дела?", "pasted": [], "keys": []}

    def hotkey(keys):
        state["keys"].append(tuple(keys))
        if tuple(keys) == ("ctrl", "c") and state["selected"]:
            state["clipboard"] = state["selected"]
        if tuple(keys) == ("ctrl", "v"):
            state["pasted"].append(state["clipboard"])

    monkeypatch.setattr(automation, "get_clipboard", lambda: state["clipboard"])
    monkeypatch.setattr(automation, "set_clipboard", lambda text: state.__setitem__("clipboard", text))
    monkeypatch.setattr(automation, "press_hotkey", hotkey)
    monkeypatch.setattr(replies, "target_window", lambda: FakeWindow())
    monkeypatch.setattr(replies, "pending", lambda: None)
    monkeypatch.setattr(win, "focus", lambda window, timeout_s=2.0: "")
    monkeypatch.setattr(win, "enumerate_windows", lambda: (FakeWindow(),))
    monkeypatch.setattr(selection.time, "sleep", lambda s: None)
    return state


def test_grab_copies_selection_and_restores_clipboard(desk):
    text, hwnd = selection.grab()
    assert (text, hwnd) == ("Привет, как дела?", 42)
    assert desk["clipboard"] == "старое"


def test_nothing_selected_is_explained(desk):
    desk["selected"] = ""
    with pytest.raises(selection.SelectionError, match="выдели"):
        selection.grab()


def test_replace_pastes_result_into_same_window(desk):
    selection.remember(42, "translate", "Hi, how are you?")
    assert selection.wants_replace("замени")
    assert selection.replace() == "Заменила."
    assert desk["pasted"] == ["Hi, how are you?"] and desk["clipboard"] == "старое"
    assert not selection.wants_replace("замени")


@pytest.mark.parametrize("phrase, mode", [
    ("переведи это", "translate"), ("объясни выделенное", "explain"), ("перепиши это вежливее", "polite"),
    ("исправь ошибки в этом тексте", "fix"), ("сократи это", "shorten"), ("перефразируй этот кусок", "rewrite"),
    ("исправь эту ошибку", None), ("напиши маме привет", None), ("переведи на английский привет", None),
])
def test_modes(phrase, mode):
    assert selection.mode_of(phrase) == mode
