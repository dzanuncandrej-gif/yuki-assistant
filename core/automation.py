"""Действия над системой: ввод, буфер обмена, звук, медиа, яркость, питание, снимки, статистика.

Приложения, окна и файлы вынесены в core/apps.py, core/windows.py и core/files.py.
Здесь нет ничего про распознавание речи — только работа с ОС.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Sequence
from urllib.parse import quote_plus

import psutil

# --- медиа-клавиши через WinAPI ---
_VK = {
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
    "play_pause": 0xB3,
    "next": 0xB0,
    "prev": 0xB1,
    "stop": 0xB2,
}
_KEYEVENTF_KEYUP = 0x0002

SITES: dict[str, str] = {
    "ютуб": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "гугл": "https://www.google.com",
    "google": "https://www.google.com",
    "почта": "https://mail.google.com",
    "гитхаб": "https://github.com",
    "github": "https://github.com",
    "википедия": "https://ru.wikipedia.org",
    "хабр": "https://habr.com",
    "телеграм веб": "https://web.telegram.org",
    "чат гпт": "https://chat.openai.com",
    "чатгпт": "https://chat.openai.com",
    "chatgpt": "https://chat.openai.com",
    "вконтакте": "https://vk.com",
    "вк": "https://vk.com",
    "vk": "https://vk.com",
    "одноклассники": "https://ok.ru",
    "яндекс": "https://ya.ru",
    "яндекс музыка": "https://music.yandex.ru",
    "кинопоиск": "https://www.kinopoisk.ru",
    "авито": "https://www.avito.ru",
    "озон": "https://www.ozon.ru",
    "вайлдберриз": "https://www.wildberries.ru",
    "вб": "https://www.wildberries.ru",
    "твич": "https://www.twitch.tv",
    "twitch": "https://www.twitch.tv",
    "реддит": "https://www.reddit.com",
    "переводчик": "https://translate.google.com",
    "карты": "https://yandex.ru/maps",
    "гугл диск": "https://drive.google.com",
    "тикток": "https://www.tiktok.com",
    "инстаграм": "https://www.instagram.com",
    "пинтерест": "https://www.pinterest.com",
    "браузер": "https://www.google.com",
}


class ActionError(RuntimeError):
    """Действие не выполнено — текст исключения уходит пользователю голосом."""


# ---------------------------------------------------------------- клавиатура и мышь


def _tap(key: str, times: int = 1) -> None:
    code = _VK[key]
    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(code, 0, 0, 0)
        user32.keybd_event(code, 0, _KEYEVENTF_KEYUP, 0)


def _pyautogui():
    try:
        import pyautogui
    except ImportError as err:  # pragma: no cover — зависит от окружения
        raise ActionError("модуль pyautogui не установлен") from err
    pyautogui.FAILSAFE = False
    return pyautogui


# --- ввод с клавиатуры ---
#
# Антивирусы (например «Безопасный ввод» Kaspersky) блокируют SendInput и keybd_event,
# когда активно защищённое приложение: мессенджер, банк-клиент. Тогда SendInput возвращает 0
# событий, и текст просто пропадает. В этом случае символы отправляются окну сообщениями
# WM_CHAR — этот путь идёт мимо низкоуровневых перехватчиков и работает в Qt-приложениях.

INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002

VK_CODES: dict[str, int] = {
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "pageup": 0x21, "pagedown": 0x22,
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "insert": 0x2D,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT(ctypes.Structure):
    """Структура ввода Windows.

    Объединение обязано содержать все три варианта, хотя нужен только
    клавиатурный. Размер структуры — часть договора с системой: на 64-разрядной
    Windows `SendInput` ждёт сорок байт (самый крупный вариант — мышиный) и молча
    отклоняет всё остальное, возвращая ноль.

    Раньше в объединении лежал один клавиатурный вариант, структура выходила в
    тридцать два байта, и ни одно событие не проходило. Ошибка пряталась за
    запасными путями: текст всё равно печатался сообщениями окна, поэтому казалось,
    что ввод работает. А сочетания клавиш сообщениями не передать — и любое
    «нажми Ctrl+S» отвечало, что ввод заблокирован защитой системы, хотя ничего
    заблокировано не было.
    """

    class _Union(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _Union)]


def _send(events: list[_INPUT]) -> bool:
    """True, если система приняла события. False — ввод заблокирован защитой."""
    if not events:
        return True
    array = (_INPUT * len(events))(*events)
    sent = ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    return int(sent) == len(events)


def _key_event(vk: int, scan: int, flags: int) -> _INPUT:
    item = _INPUT(type=INPUT_KEYBOARD)
    item.ki = _KEYBDINPUT(vk, scan, flags, 0, None)
    return item


def _vk(name: str) -> int:
    key = name.strip().lower()
    if key in VK_CODES:
        return VK_CODES[key]
    if len(key) == 1:
        return ctypes.windll.user32.VkKeyScanW(ord(key)) & 0xFF
    raise ActionError(f"неизвестная клавиша: {name}")


def _target_hwnd() -> int:
    """Окно, которому реально принадлежит клавиатурный фокус."""
    user32 = ctypes.windll.user32
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return 0
    import win32process

    try:
        target_thread = win32process.GetWindowThreadProcessId(foreground)[0]
        own_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = user32.AttachThreadInput(own_thread, target_thread, True)
        try:
            focused = user32.GetFocus()
        finally:
            if attached:
                user32.AttachThreadInput(own_thread, target_thread, False)
    except Exception:  # noqa: BLE001 — не удалось подключиться к чужому потоку
        focused = 0
    return int(focused or foreground)


def _post_text(text: str) -> bool:
    hwnd = _target_hwnd()
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    for char in text:
        if char == "\n":
            user32.PostMessageW(hwnd, WM_KEYDOWN, 0x0D, 0)
            user32.PostMessageW(hwnd, WM_KEYUP, 0x0D, 0)
            continue
        user32.PostMessageW(hwnd, WM_CHAR, ord(char), 0)
    time.sleep(0.05 + min(0.5, len(text) * 0.004))
    return True


def _post_key(vk: int, times: int = 1) -> bool:
    hwnd = _target_hwnd()
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    for _ in range(max(1, times)):
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)
        time.sleep(0.015)
    time.sleep(0.1)
    return True


def press_key(key: str, times: int = 1) -> str:
    vk = _vk(key)
    events: list[_INPUT] = []
    for _ in range(max(1, int(times))):
        events.append(_key_event(vk, 0, 0))
        events.append(_key_event(vk, 0, KEYEVENTF_KEYUP))
    if not _send(events):
        _post_key(vk, int(times))
    _screen_changed()
    return key


def press_hotkey(keys: Sequence[str]) -> str:
    codes = [_vk(str(key)) for key in keys]
    if not codes:
        raise ActionError("не указаны клавиши")
    events = [_key_event(code, 0, 0) for code in codes]
    events += [_key_event(code, 0, KEYEVENTF_KEYUP) for code in reversed(codes)]
    if not _send(events):
        if len(codes) > 1:
            # сочетание с модификатором сообщениями окна не воспроизвести, а нажать одну
            # клавишу вместо сочетания опаснее, чем честно отказаться
            raise ActionError(
                "сочетание клавиш заблокировано защитой системы (например «Безопасный ввод» Kaspersky)"
            )
        _post_key(codes[-1])
    _screen_changed()
    return "+".join(str(key) for key in keys)


# ---------------------------------------------------------------- мышь


def _screen_changed() -> None:
    """Сообщает глазам, что экран изменился.

    Дерево интерфейса кэшируется на доли секунды ради скорости. После щелчка или
    ввода оно устаревает мгновенно, и без этого сигнала следующий взгляд вернул бы
    картину до действия — помощник щёлкал бы по кнопке, которой уже нет, или
    повторял бы то, что только что сделал.
    """
    try:
        from . import screen

        screen.invalidate()
    except Exception:  # noqa: BLE001 — без глаз ввод всё равно должен работать
        pass


def screen_size() -> tuple[int, int]:
    size = _pyautogui().size()
    return int(size[0]), int(size[1])


def mouse_position() -> tuple[int, int]:
    position = _pyautogui().position()
    return int(position[0]), int(position[1])


def mouse_move(x: int, y: int, duration: float = 0.15) -> tuple[int, int]:
    width, height = screen_size()
    target = (max(0, min(width - 1, int(x))), max(0, min(height - 1, int(y))))
    _pyautogui().moveTo(target[0], target[1], duration=duration)
    return target


def mouse_click(
    x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1
) -> tuple[int, int]:
    gui = _pyautogui()
    if x is not None and y is not None:
        mouse_move(x, y)
    gui.click(button=button if button in ("left", "right", "middle") else "left", clicks=max(1, int(clicks)))
    _screen_changed()
    return mouse_position()


def mouse_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.4) -> str:
    gui = _pyautogui()
    mouse_move(x1, y1)
    gui.mouseDown()
    gui.moveTo(int(x2), int(y2), duration=duration)
    gui.mouseUp()
    return f"{x1},{y1} → {x2},{y2}"


def scroll(amount: int = -600) -> int:
    """Прокрутка колесом: отрицательное значение — вниз."""
    _pyautogui().scroll(int(amount))
    _screen_changed()
    return int(amount)


def type_text(text: str) -> str:
    """Печатает текст в активное окно.

    Порядок попыток: SendInput с юникодом (работает везде и не трогает буфер обмена),
    затем сообщения WM_CHAR — на случай, когда антивирус блокирует эмуляцию клавиатуры.
    """
    if not text:
        return text
    events: list[_INPUT] = []
    for char in text:
        code = ord(char)
        events.append(_key_event(0, code, KEYEVENTF_UNICODE))
        events.append(_key_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    if _send(events):
        time.sleep(0.05 + min(0.4, len(text) * 0.003))
        _screen_changed()
        return text
    if _post_text(text):
        _screen_changed()
        return text
    raise ActionError("ввод заблокирован защитой системы — окно не приняло текст")


def send_message(text: str) -> str:
    """Печатает текст и жмёт Enter — для мессенджеров с активным полем ввода."""
    type_text(text)
    time.sleep(0.15)
    press_key("enter")
    return text


# ---------------------------------------------------------------- буфер обмена


def get_clipboard() -> str | None:
    try:
        import pyperclip

        return pyperclip.paste()
    except Exception:  # noqa: BLE001 — на некоторых системах pyperclip не находит бэкенд
        pass
    try:
        import win32clipboard
    except ImportError:
        return None
    try:
        win32clipboard.OpenClipboard()
        try:
            return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001 — буфер может быть занят или пуст
        return None


def set_clipboard(text: str) -> None:
    try:
        import pyperclip

        pyperclip.copy(text)
        return
    except Exception:  # noqa: BLE001 — падаем на нативный WinAPI ниже
        pass
    try:
        import win32clipboard
    except ImportError as err:
        raise ActionError("буфер обмена недоступен: нет pywin32") from err
    for attempt in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return
        except Exception:  # noqa: BLE001 — другой процесс держит буфер, пробуем ещё
            time.sleep(0.05 * (attempt + 1))
    raise ActionError("буфер обмена занят другим приложением")


# ---------------------------------------------------------------- звук и медиа


def _audio_endpoint():
    """IAudioEndpointVolume устройства вывода по умолчанию.

    В свежем pycaw GetSpeakers отдаёт обёртку AudioDevice со свойством EndpointVolume;
    в старом — сырой IMMDevice, который нужно активировать вручную.
    """
    from pycaw.pycaw import AudioUtilities

    device = AudioUtilities.GetSpeakers()
    endpoint = getattr(device, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


def volume_get() -> int:
    try:
        return int(round(_audio_endpoint().GetMasterVolumeLevelScalar() * 100))
    except Exception as err:  # noqa: BLE001 — нет pycaw или звукового устройства
        raise ActionError("не удалось прочитать громкость") from err


def volume_set(percent: int) -> int:
    value = max(0, min(100, int(percent)))
    try:
        _audio_endpoint().SetMasterVolumeLevelScalar(value / 100.0, None)
    except Exception:  # noqa: BLE001 — откатываемся на медиа-клавиши
        _tap("volume_up" if value > 50 else "volume_down", 10)
    return value


def volume_step(delta: int) -> int:
    try:
        return volume_set(volume_get() + delta)
    except ActionError:
        _tap("volume_up" if delta > 0 else "volume_down", max(1, abs(delta) // 2))
        return -1


def mute_toggle() -> str:
    try:
        endpoint = _audio_endpoint()
        muted = not bool(endpoint.GetMute())
        endpoint.SetMute(muted, None)
        return "выключен" if muted else "включён"
    except Exception:  # noqa: BLE001
        _tap("mute")
        return "переключен"


def media(action: str) -> str:
    _tap(action)
    return action


# ---------------------------------------------------------------- экран и питание


def brightness_get() -> int:
    try:
        import screen_brightness_control as sbc

        values = sbc.get_brightness()
        if values:
            return int(values[0])
    except Exception:  # noqa: BLE001 — монитор может не поддерживать DDC/CI
        pass
    raise ActionError("монитор не сообщает яркость")


def brightness_set(percent: int) -> int:
    value = max(0, min(100, int(percent)))
    try:
        import screen_brightness_control as sbc

        sbc.set_brightness(value)
    except Exception as err:  # noqa: BLE001
        raise ActionError("монитор не поддерживает программную яркость") from err
    return value


def lock_workstation() -> None:
    ctypes.windll.user32.LockWorkStation()


def sleep_pc() -> None:
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], shell=False)


def minimize_all() -> None:
    press_hotkey(("win", "d"))


# ---------------------------------------------------------------- питание

POWER_DELAY_S = 20

_POWER_ARGS = {
    "shutdown": ("/s",),
    "restart": ("/r",),
    "logoff": ("/l",),
    "hibernate": ("/h",),
}


def power(action: str, delay_s: int = POWER_DELAY_S) -> int:
    """Выключение, перезагрузка, выход или гибернация с отсрочкой.

    Отсрочка — намеренная: команду можно отменить голосом («отмена выключения»),
    если ассистент неверно расслышал.
    """
    args = _POWER_ARGS.get(action)
    if args is None:
        raise ActionError(f"неизвестное действие питания: {action}")
    if action in ("logoff", "hibernate"):
        subprocess.Popen(["shutdown", *args], shell=False)
        return 0
    subprocess.Popen(["shutdown", *args, "/t", str(max(0, int(delay_s)))], shell=False)
    return delay_s


def power_cancel() -> None:
    subprocess.run(["shutdown", "/a"], shell=False, capture_output=True, check=False)


def empty_recycle_bin() -> None:
    """SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND."""
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x00000001 | 0x00000002 | 0x00000004)
    if result not in (0, -2147418113):  # S_OK либо «корзина уже пуста»
        raise ActionError("не удалось очистить корзину")


def kill_process(name: str) -> str:
    """Жёсткое завершение по имени процесса — когда обычное закрытие не помогло."""
    from .apps import PROTECTED

    needle = name.strip().lower().removesuffix(".exe")
    if not needle:
        raise ActionError("не понял, какой процесс завершить")
    killed: list[str] = []
    for process in psutil.process_iter(["name"]):
        process_name = str(process.info.get("name") or "").lower()
        if not process_name or process_name in PROTECTED:
            continue
        if needle in process_name.removesuffix(".exe"):
            try:
                process.kill()
                killed.append(process_name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    if not killed:
        raise ActionError(f"процесс «{name}» не найден")
    return ", ".join(sorted(set(killed)))


def network_adapter(enable: bool, name: str = "Wi-Fi") -> str:
    """Включение или отключение сетевого адаптера. Требует прав администратора."""
    state = "enable" if enable else "disable"
    result = subprocess.run(
        ["netsh", "interface", "set", "interface", f"name={name}", f"admin={state}"],
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ActionError("нужны права администратора для управления сетью")
    return name


def screenshot(directory: Path | None = None) -> Path:
    target_dir = directory or (Path.home() / "Pictures" / "Юки")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png"
    _pyautogui().screenshot(str(target))
    return target


# ---------------------------------------------------------------- сеть


def open_url(url: str) -> str:
    webbrowser.open(url)
    return url


def web_search(query: str) -> str:
    return open_url(f"https://www.google.com/search?q={quote_plus(query)}")


def open_site(name: str) -> str | None:
    """Открывает сайт, если названо именно его имя.

    Сравнение по целому названию, а не по вхождению: «вк» внутри «открой вкладку»
    не должно открывать ВКонтакте. Сначала длинные названия — «яндекс музыка»
    раньше «яндекса».
    """
    query = re.sub(r"\s+", " ", name.strip().lower().strip(" .,!?"))
    query = re.sub(r"^(?:сайт|страницу)\s+", "", query)
    for key in sorted(SITES, key=len, reverse=True):
        if query == key or query in (f"{key}.ru", f"{key}.com"):
            open_url(SITES[key])
            return key
    if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:ru|com|org|net|io|tv|me|dev|app|рф)", query):
        open_url(f"https://{query}")
        return query
    return None


# ---------------------------------------------------------------- система


def system_stats() -> str:
    cpu = psutil.cpu_percent(interval=0.3)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path.home().anchor or "C:\\"))
    parts = [
        f"процессор {cpu:.0f} процентов",
        f"память {memory.percent:.0f} процентов из {memory.total / 1024 ** 3:.0f} гигабайт",
        f"диск занят на {disk.percent:.0f} процентов",
    ]
    battery = psutil.sensors_battery()
    if battery is not None:
        state = "заряжается" if battery.power_plugged else "от батареи"
        parts.append(f"батарея {battery.percent:.0f} процентов, {state}")
    uptime = time.time() - psutil.boot_time()
    parts.append(f"система работает {int(uptime // 3600)} часов")
    return ", ".join(parts)


def run_command(command: str, timeout_s: float = 15.0) -> str:
    """Выполняет команду оболочки по явной просьбе пользователя и возвращает начало вывода."""
    if not command.strip():
        raise ActionError("пустая команда")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout_s,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as err:
        raise ActionError(f"команда не завершилась за {timeout_s:.0f} секунд") from err
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return f"код возврата {result.returncode}"
    head = " ".join(output.splitlines()[:3])
    return head[:300] + ("…" if len(head) > 300 else "")
