"""Прогон живых фраз через быстрый разбор команд — без побочных действий.

Каждое действие с системой (запуск программ, ввод, сеть, мессенджеры) подменено
записью «что было бы сделано». Так видно, куда уходит фраза, не открывая ничего
на компьютере:

    python scripts/probe_routing.py            все фразы
    python scripts/probe_routing.py телеграм   только содержащие слово
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import apps, automation, browser, commands, files, media, messengers, outbox, web  # noqa: E402
from core import text as text_utils  # noqa: E402
from core import windows as win  # noqa: E402

CALLS: list[str] = []


def _record(label: str, result: object = None):  # noqa: ANN202
    def fake(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        shown = ", ".join([repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()])
        CALLS.append(f"{label}({shown})")
        return result(*args, **kwargs) if callable(result) else result

    return fake


def _launch(name: str, *_: object, **__: object) -> str:
    try:
        target = apps.resolve(name)
    except apps.AppError as err:
        CALLS.append(f"launch({name!r}) -> ОШИБКА {err}")
        raise
    CALLS.append(f"launch({name!r}) -> {target.kind}:{target.name}")
    return target.name


def install_fakes() -> None:
    apps.launch = _launch
    apps.launch_and_focus = _launch
    apps.close = _record("apps.close", lambda name: name)
    for name in ("type_text", "send_message", "press_key", "press_hotkey", "mouse_click",
                 "media", "minimize_all", "power", "power_cancel", "lock_workstation",
                 "sleep_pc", "empty_recycle_bin", "run_command", "set_clipboard"):
        setattr(automation, name, _record(f"automation.{name}", lambda *a, **k: "ok"))
    automation.volume_set = _record("automation.volume_set", lambda value: value)
    automation.volume_step = _record("automation.volume_step", lambda delta: 50 + delta)
    automation.volume_get = _record("automation.volume_get", 50)
    automation.mute_toggle = _record("automation.mute_toggle", "выключен")
    automation.screenshot = _record("automation.screenshot", lambda: Path("shot.png"))
    automation.open_url = _record("automation.open_url", lambda url: url)
    automation.kill_process = _record("automation.kill_process", lambda name: name)
    automation.network_adapter = _record("automation.network_adapter", "Wi-Fi")
    for name in ("open_url", "play_music", "play_video", "weather", "news", "search_web",
                 "forecast", "youtube_video_id"):
        if hasattr(web, name):
            setattr(web, name, _record(f"web.{name}", lambda *a, **k: "ok"))
    web.news = _record("web.news", ())
    for name in ("open_url", "search", "go_to"):
        setattr(browser, name, _record(f"browser.{name}", "страница"))
    messengers.send = _record("messengers.send", lambda app, contact, message: contact)

    def fake_prepare(service: str, contact: str, *_: object, **__: object) -> outbox.Draft:
        CALLS.append(f"outbox.prepare({service!r}, {contact!r}) -> ищет «{outbox.search_query(contact)}»")
        return outbox.Draft(service=outbox.resolve_service(service), asked=contact,
                            found=outbox.search_query(contact).capitalize())

    outbox.prepare = fake_prepare
    outbox.open_found = _record("outbox.open_found", lambda draft: draft.found)
    outbox.deliver = _record("outbox.deliver", lambda draft, text: draft.found)
    for name in ("play_music", "play_video", "search_youtube", "next_track"):
        setattr(media, name, _record(f"media.{name}", lambda *a, **k: (a[0] if a and a[0] else "музыка")))
    for name in ("delete", "copy", "move", "rename", "write_text", "make_folder", "open_path",
                 "open_folder", "browse", "read_text"):
        setattr(files, name, _record(f"files.{name}", lambda *a, **k: Path("x")))
    files.locate = _record("files.locate", lambda name, scope="home": Path(name))
    files.search = _record("files.search", ())
    for name in ("focus", "minimize", "maximize", "close", "minimize_active", "maximize_active",
                 "close_active"):
        setattr(win, name, _record(f"win.{name}", "окно"))
    win.find = _record("win.find", lambda name: name)
    win.screen_context = _record("win.screen_context", "экран")


PHRASES = """
открой телеграм
открой телеграмм
открой телегу
запусти телеграм
открой телеграм и напиши Владимиру привет
открой телеграм и напиши контакту Владимир привет
напиши Владимиру привет
напиши владимиру привет как дела
напиши Владимиру в телеграм привет
напиши в телеграме Владимиру привет
отправь Владимиру привет в телеграме
напиши сообщение Владимиру привет
отправь сообщение Владимиру что я опоздаю
напиши маме что я скоро буду
скажи папе в телеграме что я дома
напиши в тг Вове привет
напиши контакту Владимир привет
открой чат с Владимиром
найди в телеграме Владимира и напиши привет
напиши Владимиру
напечатай привет мир
напиши привет
включи музыку
включи какую-нибудь музыку
включи другую музыку
включи другую песню
поставь другой трек
следующий трек
переключи песню
включи Моргенштерна
включи песню Believer
включи Imagine Dragons Believer
поставь Кино Группа крови
включи трек Скриптонит Космос
включи видео про котиков
включи видео как приготовить борщ
найди на ютубе обзор айфона
покажи видео про космос
включи фильм Интерстеллар
открой ютуб и включи видео про котиков
открой ютуб
открой youtube
выключи музыку
пауза
продолжи
сделай погромче
громкость 30
какая погода
какая погода в Москве
который час
какие новости
открой хром
открой браузер
закрой хром
открой стим
запусти кс2
открой дискорд
открой вк
открой блокнот и напиши привет
найди в интернете рецепт борща
кто такой Илон Маск
сколько стоит биткоин
что такое чёрная дыра
сделай скриншот
сверни всё
открой playstation
открой display settings
удали сообщение
выключи компьютер
привет как дела
расскажи анекдот
""".strip().splitlines()


def main() -> int:
    install_fakes()
    needle = " ".join(sys.argv[1:]).lower()
    for phrase in PHRASES:
        if needle and needle not in phrase.lower():
            continue
        CALLS.clear()
        clean = text_utils.normalize(phrase)
        try:
            outcome = commands.handle_plan(clean)
            answer = outcome.answer
            route = "КОМАНДА" if outcome.answer and not outcome.remainder else (
                f"ЧАСТЬ, агенту: «{outcome.remainder}»" if outcome.answer else "АГЕНТ")
            if outcome.failure:
                answer = f"{answer or ''} | неудача: {outcome.failure}"
        except Exception as err:  # noqa: BLE001
            answer, route = f"ИСКЛЮЧЕНИЕ {err!r}", "ОШИБКА"
        commands._clear_pending()  # каждая фраза проверяется с чистого листа
        from core import questions

        query = questions.web_query(clean)
        if route == "АГЕНТ" and query is not None:
            route = f"ПОИСК: «{query}»"
        print(f"\n» {phrase}\n  [{route}] {answer}")
        for call in CALLS:
            print(f"    · {call}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
