"""Сравнение имён адресатов — самая дорогая ошибка помощника.

Сообщение, ушедшее не тому человеку, вернуть нельзя, поэтому сравнение имён
намеренно строгое: лучше переспросить, чем угадать.
"""

from __future__ import annotations

from core import outbox


def test_exact_name_is_certain() -> None:
    assert outbox.similarity("Владимир", "Владимир") == 1.0


def test_short_form_matches_full_name() -> None:
    assert outbox.similarity("Ване", "Иван Кузнецов") >= outbox.MAYBE


def test_different_people_do_not_match() -> None:
    assert outbox.similarity("Владимир", "Екатерина") < outbox.MAYBE


def test_full_name_covers_the_short_one() -> None:
    """«Максим» внутри «Максим Петров» — то же имя: сказанное совпало целиком."""
    assert outbox.similarity("Максим", "Максим Петров") >= outbox.SURE


def test_other_person_with_same_surname_is_not_certain() -> None:
    """Однофамилец — не адресат: имя не совпало, отправлять без вопроса нельзя."""
    assert outbox.similarity("Максим Петров", "Сергей Петров") < outbox.SURE


def test_case_endings_are_ignored() -> None:
    assert outbox.stem("Максиму") == outbox.stem("Максимом") == "максим"


def test_search_query_uses_stem_not_case_form() -> None:
    assert outbox.search_query("Владимиру").startswith("владимир")


def test_chat_title_drops_chat_kind_prefix() -> None:
    assert outbox.chat_title("Канал, Карина Палецких") == "Карина Палецких"
    assert outbox.chat_title("Бот, Lagom VPN") == "Lagom VPN"


def test_chat_title_keeps_plain_name() -> None:
    assert outbox.chat_title("Владимир") == "Владимир"


def test_draft_without_contact_is_not_certain() -> None:
    service = outbox.resolve_service("telegram")
    draft = outbox.Draft(service=service, asked="Владимир")
    assert draft.certain is False


def test_ambiguous_draft_is_never_certain() -> None:
    """Два уверенных совпадения — всегда вопрос человеку, а не выбор наугад."""
    service = outbox.resolve_service("telegram")
    draft = outbox.Draft(service=service, asked="Владимир", found="Владимир", ambiguous=True)
    assert draft.certain is False


def test_service_aliases_resolve() -> None:
    for spoken in ("телеграм", "телеграмм", "тг"):
        assert outbox.resolve_service(spoken).key == "telegram"


def test_unknown_service_is_rejected() -> None:
    try:
        outbox.resolve_service("голубиная почта")
    except outbox.OutboxError as err:
        assert "голубиная почта" in str(err)
    else:  # pragma: no cover
        raise AssertionError("неизвестный мессенджер должен приводить к OutboxError")
