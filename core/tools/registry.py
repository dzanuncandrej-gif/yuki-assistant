"""Реестр инструментов агента: описание для модели, вызов и разбор результата.

Инструмент добавляется одним декоратором и сразу становится виден языковой модели:

    @tool("volume_set", "Ставит громкость системы", {"level": param_int("0..100")}, ["level"])
    def _volume(level: int) -> str:
        return f"громкость {automation.volume_set(level)}"

Возврат строки означает успех: она уходит в модель как результат и попадает в журнал.
Исключение означает провал — модель получит текст ошибки и сможет попробовать иначе.
"""

from __future__ import annotations

import inspect
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

Handler = Callable[..., str]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: Mapping[str, Any]
    required: tuple[str, ...]
    handler: Handler
    confirm: bool = False  # действие необратимо — спрашиваем подтверждение

    def spec(self) -> dict[str, Any]:
        """Описание в формате OpenAI/Ollama function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": dict(self.properties),
                    "required": list(self.required),
                },
            },
        }


@dataclass(frozen=True)
class Result:
    ok: bool
    text: str
    tool: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def for_model(self) -> str:
        return self.text if self.ok else f"ОШИБКА: {self.text}"


_REGISTRY: dict[str, Tool] = {}
_lock = threading.Lock()

# текст текущей просьбы: по нему проверяются необратимые действия
_request: dict[str, str] = {"text": ""}

# отложенное необратимое действие: ждёт согласия человека
_pending: dict[str, Any] = {"name": "", "arguments": {}, "until": 0.0}

# слова согласия: короткий ответ «да» после вопроса о необратимом действии
_YES = ("да", "давай", "подтвержда", "согласен", "согласна", "удаляй", "выполняй",
        "продолжай", "ок", "окей", "yes", "confirm")
_NO = ("нет", "отмена", "отставить", "стой", "не надо", "cancel", "no")

_PENDING_TTL = 120.0  # дольше двух минут человек уже не помнит, что спрашивали


def pending() -> tuple[str, Mapping[str, Any]]:
    """Действие, ожидающее согласия. Пустое имя — ничего не ждём."""
    if _pending["name"] and time.monotonic() > float(_pending["until"]):
        clear_pending()
    return str(_pending["name"]), dict(_pending["arguments"])


def remember_pending(name: str, arguments: Mapping[str, Any]) -> None:
    _pending["name"] = name
    _pending["arguments"] = dict(arguments)
    _pending["until"] = time.monotonic() + _PENDING_TTL


def clear_pending() -> None:
    _pending["name"] = ""
    _pending["arguments"] = {}
    _pending["until"] = 0.0


def answers_yes(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if any(word in lowered for word in _NO):
        return False
    return any(word in lowered for word in _YES)


def resolve_pending(text: str) -> Result | None:
    """Короткий ответ человека на вопрос о необратимом действии.

    «Да» — выполняем отложенный вызов. Что угодно другое — забываем его, чтобы
    случайное слово через десять минут ничего не стёрло.
    """
    name, arguments = pending()
    if not name:
        return None
    clear_pending()
    if not answers_yes(text):
        return Result(True, "Отменено.", name, arguments)
    return call(name, arguments, confirmed=True)


def set_request(text: str) -> None:
    """Агент кладёт сюда фразу человека перед тем, как начать вызывать инструменты."""
    _request["text"] = str(text or "").lower()


def request_text() -> str:
    return _request["text"]


def request_mentions(words: tuple[str, ...]) -> bool:
    """Просил ли человек именно об этом. Защита от инициативы модели.

    Модель, услышав обрывок постороннего разговора, охотно «наводит порядок»:
    закрывает окна, снимает процессы. Необратимые инструменты выполняются только
    если соответствующее слово прозвучало в самой просьбе.
    """
    text = _request["text"]
    if not text:
        return True  # запрос не задан (ручной вызов инструмента) — не мешаем
    return any(word in text for word in words)


def param(kind: str, description: str, **extra: Any) -> dict[str, Any]:
    return {"type": kind, "description": description, **extra}


def param_str(description: str, **extra: Any) -> dict[str, Any]:
    return param("string", description, **extra)


def param_int(description: str, **extra: Any) -> dict[str, Any]:
    return param("integer", description, **extra)


def param_bool(description: str, **extra: Any) -> dict[str, Any]:
    return param("boolean", description, **extra)


def tool(
    name: str,
    description: str,
    properties: Mapping[str, Any] | None = None,
    required: tuple[str, ...] | list[str] = (),
    *,
    confirm: bool = False,
) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        with _lock:
            _REGISTRY[name] = Tool(
                name=name,
                description=description,
                properties=properties or {},
                required=tuple(required),
                handler=handler,
                confirm=confirm,
            )
        return handler

    return decorator


def catalog() -> tuple[Tool, ...]:
    with _lock:
        return tuple(_REGISTRY.values())


def get(name: str) -> Tool | None:
    with _lock:
        return _REGISTRY.get(name)


def specs(exclude: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    return [item.spec() for item in catalog() if item.name not in exclude]


def names() -> tuple[str, ...]:
    return tuple(sorted(item.name for item in catalog()))


# ---------------------------------------------------------------- вызов

_TRUE = {"true", "да", "yes", "1", "on"}
_FALSE = {"false", "нет", "no", "0", "off"}


def _coerce(value: Any, schema: Mapping[str, Any]) -> Any:
    """Модели часто присылают числа строками — приводим к типу из схемы."""
    kind = schema.get("type")
    try:
        if kind == "integer" and not isinstance(value, bool):
            return int(float(str(value).strip().replace(",", ".")))
        if kind == "number" and not isinstance(value, bool):
            return float(str(value).strip().replace(",", "."))
        if kind == "boolean":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in _TRUE:
                return True
            if text in _FALSE:
                return False
        if kind == "string" and not isinstance(value, str):
            return str(value)
    except (TypeError, ValueError):
        return value
    return value


# Иероглифы в доводах инструмента. Многоязычная модель нет-нет да и подставит
# китайское слово вместо русского: `open_app(name=计算器)` вместо «калькулятор».
# Приложение с таким именем не находится, и дальше модель уходит выполнять задачу
# наугад. Ловим на границе: пусть лучше сразу получит понятное замечание.
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def _sanitize(key: str, value: Any) -> Any:
    """Проверяет довод перед вызовом: чужая письменность до инструмента не доходит."""
    if not isinstance(value, str) or not _CJK.search(value):
        return value
    cleaned = _CJK.sub("", value).strip()
    if not cleaned:
        raise ValueError(
            f"довод «{key}» написан иероглифами — назови его по-русски или латиницей"
        )
    return cleaned


def _prepare(target: Tool, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Оставляем только известные параметры и приводим их типы."""
    accepted = set(inspect.signature(target.handler).parameters)
    prepared: dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        if key not in accepted:
            continue
        schema = target.properties.get(key, {})
        prepared[key] = _sanitize(key, _coerce(value, schema if isinstance(schema, Mapping) else {}))
    missing = [key for key in target.required if key not in prepared or prepared[key] in (None, "")]
    if missing:
        raise ValueError(f"не хватает параметров: {', '.join(missing)}")
    return prepared


def call(name: str, arguments: Mapping[str, Any] | None = None,
         confirmed: bool = False) -> Result:
    """Выполняет инструмент. Любая ошибка превращается в результат, а не в исключение.

    Необратимые инструменты сначала не выполняются, а возвращают вопрос. Модель
    передаёт вопрос человеку, и только после явного согласия тот же вызов
    повторяется с `confirmed=True`.
    """
    target = get(name)
    if target is None:
        return Result(False, f"инструмента «{name}» нет. Доступны: {', '.join(names())}", name, arguments or {})
    try:
        prepared = _prepare(target, arguments or {})
    except ValueError as err:
        return Result(False, str(err), name, arguments or {})

    if target.confirm and not confirmed:
        remember_pending(name, prepared)
        details = ", ".join(f"{key}={value}" for key, value in prepared.items()) or "без параметров"
        return Result(
            True,
            f"ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ. Действие необратимо: {target.description} ({details}). "
            f"Спроси у человека согласие вслух и не вызывай «{name}» повторно, "
            f"пока он не ответит согласием.",
            name,
            prepared,
        )

    try:
        output = target.handler(**prepared)
    except Exception as err:  # noqa: BLE001 — текст ошибки нужен модели для второй попытки
        detail = str(err) or err.__class__.__name__
        return Result(False, detail, name, prepared)
    return Result(True, str(output), name, prepared)
