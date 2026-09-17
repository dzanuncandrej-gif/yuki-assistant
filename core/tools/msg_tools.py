"""Инструменты мессенджеров: открыть переписку и отправить сообщение по-настоящему."""

from __future__ import annotations

from .. import outbox
from .registry import param_str, tool

_APPS = ["telegram", "whatsapp", "discord", "slack", "steam"]


@tool(
    "send_message",
    "Отправляет сообщение человеку в мессенджере — единственный правильный способ кому-то "
    "написать. Сам открывает приложение, находит контакт, сверяет имя, печатает и отправляет. "
    "Не используй type_text для сообщений. Мессенджер не назван — telegram.",
    {
        "app": param_str("Мессенджер", enum=_APPS),
        "contact": param_str("Имя адресата так, как его назвал человек, например «Владимир»"),
        "text": param_str("Текст сообщения — только то, что нужно написать, без имени адресата"),
    },
    ["contact", "text"],
)
def _send_message(contact: str, text: str, app: str = "telegram") -> str:
    draft = outbox.prepare(app or "telegram", contact)
    if not draft.found:
        others = f" Похожие: {', '.join(draft.candidates)}" if draft.candidates else ""
        raise RuntimeError(f"контакт «{contact}» не найден.{others}")
    outbox.open_found(draft)
    if not draft.certain:
        raise RuntimeError(
            f"нашла «{draft.found}», но не уверена, что это «{contact}». Спроси человека, тот ли "
            "это адресат; после согласия вызови confirm_contact, затем send_to_contact"
        )
    return f"отправлено «{outbox.deliver(draft, text)}»: {text}"


@tool(
    "open_chat",
    "Открывает переписку с контактом в мессенджере, ничего не отправляя.",
    {
        "app": param_str("Мессенджер", enum=_APPS),
        "contact": param_str("Имя контакта или чата"),
    },
    ["contact"],
)
def _open_chat(contact: str, app: str = "telegram") -> str:
    draft = outbox.prepare(app or "telegram", contact)
    if not draft.found:
        raise RuntimeError(f"контакт «{contact}» не найден")
    return f"открыт чат «{outbox.open_found(draft)}»"
