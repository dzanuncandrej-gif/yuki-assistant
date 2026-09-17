"""Инструменты экрана: смотреть, находить элементы, нажимать и проверять результат.

Разделение между ними намеренное и важное.

`read_screen` и `list_controls` работают по дереву интерфейса Windows: мгновенно,
без видеокарты и с настоящими координатами. Ими решается почти всё — какие кнопки
есть, что написано в окне, появилось ли сообщение об ошибке.

`look_at_screen` будит модель зрения. Она понимает картинку и игру, но координаты
у неё выдуманные, поэтому её ответ никогда не превращается в щелчок. Модель ещё и
делит видеопамять с языковой, поэтому зовётся только там, где без неё никак.

`click_control` нажимает по имени, взяв координаты из дерева. Промахнуться он не
может: если элемента нет, инструмент говорит об этом, а не тычет наугад.
"""

from __future__ import annotations

from .. import screen
from .registry import param_bool, param_int, param_str, tool

_settings: dict[str, str] = {"ollama_url": "http://127.0.0.1:11434"}


def configure(settings: dict[str, str] | None) -> None:
    if settings:
        _settings.update({key: str(value) for key, value in settings.items()})


@tool(
    "read_screen",
    "Что сейчас на экране: активное окно, поле ввода под фокусом, доступные кнопки, "
    "текст окна и сообщение об ошибке, если оно есть. Работает мгновенно и точно — "
    "вызывай его ПЕРВЫМ, прежде чем что-то нажимать или спрашивать модель зрения.",
)
def _read_screen() -> str:
    state = screen.scene(fresh=True)
    return state.summary()


@tool(
    "list_controls",
    "Список того, на что сейчас можно нажать в активном окне, с ролями. "
    "Нужен, чтобы выбрать точное имя для click_control.",
    {"filter": param_str("Показать только подходящие по имени, необязательно")},
)
def _list_controls(filter: str = "") -> str:  # noqa: A002 — имя видно модели
    items = screen.matches(filter, limit=25) if filter.strip() else screen.clickables()
    if not items:
        return "нажимать сейчас не на что"
    return "; ".join(f"{item.name} [{item.role}]" for item in items if item.name)


@tool(
    "click_control",
    "Нажимает кнопку, пункт меню, вкладку или ссылку по её названию на экране. "
    "Координаты берутся из системы, поэтому промаха не будет. Если элемента нет — "
    "вернётся ошибка со списком доступных, наугад ничего не нажимается.",
    {
        "name": param_str("Название элемента так, как оно написано на экране"),
        "double": param_bool("Двойной щелчок, по умолчанию нет"),
    },
    ["name"],
)
def _click_control(name: str, double: bool = False) -> str:
    result = screen.click(name, double=bool(double))
    screen.wait_until_stable(timeout_s=2.5)
    after = screen.scene(fresh=True)
    tail = f" Теперь окно «{after.title}»." if after.title else ""
    return result + tail + (f" Диалог: {after.dialog}." if after.dialog else "")


@tool(
    "type_into",
    "Ставит курсор в поле ввода по его названию и печатает туда текст.",
    {
        "field": param_str("Название поля ввода на экране"),
        "text": param_str("Что напечатать"),
        "enter": param_bool("Нажать Enter после ввода"),
    },
    ["field", "text"],
)
def _type_into(field: str, text: str, enter: bool = False) -> str:
    from .. import automation

    target = screen.focus_element(field)
    automation.type_text(text)
    if enter:
        automation.press_key("enter")
    screen.invalidate()
    screen.wait_until_stable(timeout_s=2.0)
    return f"напечатала в «{target.name}»: {text[:80]}"


@tool(
    "wait_for_control",
    "Ждёт, пока на экране появится (или исчезнет) элемент с таким названием. "
    "Так проверяется, что действие сработало: окно открылось, кнопка пропала.",
    {
        "name": param_str("Название элемента"),
        "seconds": param_int("Сколько ждать, 1..30"),
        "gone": param_bool("Ждать исчезновения, а не появления"),
    },
    ["name"],
)
def _wait_for_control(name: str, seconds: int = 8, gone: bool = False) -> str:
    limit = max(1, min(30, int(seconds)))
    found = screen.wait_for(name, timeout_s=limit, gone=bool(gone))
    if gone:
        return f"«{name}» исчез с экрана"
    if found is None:
        raise RuntimeError(f"«{name}» не появился за {limit} с")
    return f"«{found.name}» на экране, в точке {found.center[0]},{found.center[1]}"


@tool(
    "read_window_text",
    "Весь текст активного окна так, как его знает сама система — без распознавания "
    "картинки и без домыслов. Этим читаются сообщения, списки и содержимое полей.",
)
def _read_window_text() -> str:
    text = screen.screen_text()
    return text or "в окне нет читаемого текста — попробуй look_at_screen"


@tool(
    "list_windows_on_screen",
    "Какие окна открыты и где они расположены на экране.",
)
def _windows_on_screen() -> str:
    items = screen.windows_list()
    if not items:
        return "открытых окон нет"
    rows = [
        f"{'активно ' if item.focused else ''}«{item.name}» ({item.width}x{item.height})"
        for item in items[:12]
    ]
    return "; ".join(rows)
