"""Робот-тестировщик для окон tkinter: нажимает всё сам, пока окно скрыто.

Пробный запуск «окно прожило четыре секунды» ловит только падение при старте.
А калькулятор, который падает на «=» с пустым вводом, или змейка, падающая на
первом повороте, такую проверку проходят. Робот запускает программу с
подменённым `mainloop`: окно спрятано, каждая кнопка нажимается, по окну
прогоняются стрелки, пробел, Enter и цифры, игровой цикл крутится пару секунд.
Любое исключение в обработчике — это ошибка, которую агент потом исправит.
Диалоги (`messagebox`, `simpledialog`, `filedialog`) подменены, чтобы ничего
не ждало человека.
"""

from __future__ import annotations

HARNESS = r'''
import os, re, runpy, sys, time, traceback
import tkinter as tk

ENTRY = sys.argv[1]
SKIP = re.compile(r"выход|выйти|закрыть|quit|exit|close|удалить\s+вс|очистить\s+историю", re.I)
KEYS = ("Left", "Right", "Up", "Down", "space", "Return", "1", "2", "plus", "5", "equal", "BackSpace",
        "w", "a", "s", "d", "p", "r", "Escape")
errors = []


def record(*info):
    errors.append("".join(traceback.format_exception(*info)) if info else traceback.format_exc())


tk.Tk.report_callback_exception = lambda self, *info: record(*info)

# диалоги не должны ждать человека
try:
    from tkinter import filedialog, messagebox, simpledialog
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, name, lambda *a, **k: "ok")
    for name in ("askyesno", "askokcancel", "askretrycancel", "askyesnocancel", "askquestion"):
        setattr(messagebox, name, lambda *a, **k: True)
    for name in ("askstring", "askinteger", "askfloat"):
        setattr(simpledialog, name, lambda *a, **k: None)
    for name in dir(filedialog):
        if name.startswith("ask"):
            setattr(filedialog, name, lambda *a, **k: "")
except Exception:
    pass

_init = tk.Tk.__init__


def hidden_init(self, *args, **kwargs):
    _init(self, *args, **kwargs)
    self.withdraw()


tk.Tk.__init__ = hidden_init


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            root.update()
        except tk.TclError:
            return False
        time.sleep(0.01)
    return True


def buttons(widget):
    for child in widget.winfo_children():
        if child.winfo_class() in ("Button", "TButton"):
            yield child
        yield from buttons(child)


def robot(self, n=0):
    root = self if isinstance(self, tk.Tk) else self._root()
    root.withdraw()
    if not pump(root, 0.3):
        return
    clicked = 0
    for button in list(buttons(root)):
        try:
            label = str(button.cget("text"))
            if SKIP.search(label) or str(button.cget("state")) == "disabled":
                continue
            button.invoke()
            clicked += 1
        except tk.TclError:
            continue
        except Exception:
            record()
        if not pump(root, 0.02):
            break
    pressed = 0
    targets = [root] + [w for w in root.winfo_children() if w.winfo_class() in ("Canvas", "Entry", "TEntry", "Frame")]
    for key in KEYS:
        for target in targets[:3]:
            try:
                target.event_generate(f"<KeyPress-{key}>", when="tail")
                pressed += 1
            except tk.TclError:
                pass
        if not pump(root, 0.05):
            break
    pump(root, 1.5)  # игровой цикл на after() должен пережить пару секунд
    print(f"SMOKE clicked={clicked} keys={pressed} errors={len(errors)}")
    for item in errors[:3]:
        print(item, file=sys.stderr)
    try:
        root.destroy()
    except tk.TclError:
        pass
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(1 if errors else 0)


tk.Misc.mainloop = robot
sys.argv = [ENTRY]
sys.path.insert(0, os.getcwd())
try:
    runpy.run_path(ENTRY, run_name="__main__")
except SystemExit:
    pass
except Exception:
    record()
    print(f"SMOKE clicked=0 keys=0 errors={len(errors)}")
    print(errors[-1], file=sys.stderr)
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(1)
print("SMOKE no-mainloop")
'''
