"""Инструменты отправки сообщений с проверкой адресата.

Отправка нарочно разделена надвое. `find_contact` только ищет и докладывает, кого
нашёл; `send_to_contact` отправляет уже найденному. Между ними стоит человек.

Одним вызовом отправить тоже можно, но лишь тогда, когда имя совпало уверенно.
Похожее имя без подтверждения не отправляется никогда: письмо, ушедшее не тому,
не отзывается обратно.
"""

from __future__ import annotations

from .. import outbox
from .registry import param_str, tool


@tool(
    "find_contact",
    "Открывает мессенджер (telegram, discord, steam, whatsapp, slack) и ищет контакт "
    "по имени. Ничего не отправляет — только докладывает, кого нашёл. Вызывай это "
    "первым, когда человек просит кому-то написать.",
    {
        "service": param_str("Мессенджер", enum=["telegram", "discord", "steam",
                                                 "whatsapp", "slack"]),
        "contact": param_str("Имя контакта так, как назвал человек"),
    },
    ["service", "contact"],
)
def _find_contact(service: str, contact: str) -> str:
    draft = outbox.prepare(service, contact)
    if not draft.found:
        others = ", ".join(draft.candidates) if draft.candidates else "ничего похожего"
        raise RuntimeError(f"контакт «{contact}» не найден. В списке: {others}")
    outbox.open_found(draft)
    if draft.certain:
        return (f"нашла «{draft.found}» и открыла переписку. "
                "Спроси у человека, что написать, и вызови send_to_contact")
    return (f"нашла «{draft.found}», но это не точное совпадение с «{draft.asked}». "
            f"Другие варианты: {', '.join(draft.candidates)}. "
            "Спроси у человека, тот ли это адресат, и только потом отправляй")


@tool(
    "send_to_contact",
    "Отправляет сообщение контакту, найденному через find_contact. Перед отправкой "
    "ещё раз сверяет, чей чат открыт на экране.",
    {"text": param_str("Текст сообщения")},
    ["text"],
)
def _send_to_contact(text: str) -> str:
    draft = outbox.current()
    if draft is None:
        raise RuntimeError("сначала найди контакт через find_contact")
    if not draft.certain and not draft.confirmed:
        raise RuntimeError(
            f"адресат «{draft.found}» не подтверждён человеком — не отправляю. "
            "Спроси его вслух: тот ли это контакт"
        )
    return f"отправила «{draft.found}»: {outbox.deliver(draft, text)}"


@tool(
    "confirm_contact",
    "Отмечает, что человек подтвердил адресата вслух. После этого можно отправлять.",
)
def _confirm_contact() -> str:
    draft = outbox.current()
    if draft is None:
        raise RuntimeError("сейчас никого не выбирали")
    draft.confirmed = True
    return f"адресат подтверждён: {draft.found}"


@tool(
    "cancel_message",
    "Отменяет подготовленное сообщение — ничего не отправляется.",
)
def _cancel_message() -> str:
    return outbox.cancel()
