"""Сравнение имён адресатов — самая дорогая ошибка помощника.

Сообщение, ушедшее не тому человеку, вернуть нельзя, поэтому сравнение имён
намеренно строгое: лучше переспросить, чем угадать.
"""

from __future__ import annotations

from core import outbox, screen


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


# ---------------------------------------------------------------- колонка выдачи


def _row(name: str, top: int, left: int = 0, right: int = 300) -> screen.Element:
    return screen.Element(name=name, role="listitem", left=left, top=top,
                          right=right, bottom=top + 60)


def test_results_zone_drops_the_opened_conversation() -> None:
    """Справа — открытая переписка. Её строки не кандидаты: щелчок по ним уводит не туда."""
    box = screen.Element(name="Поиск", role="edit", left=10, top=40, right=300, bottom=76)
    rows = (_row("Владимир", 120), _row("Владимир Петров", 900, left=620, right=1500))
    zone = outbox.results_zone(box, rows)
    assert [item.name for item in zone] == ["Владимир"]


def test_results_zone_is_ordered_top_down() -> None:
    """Порядок — как видит человек, а не как обходится дерево интерфейса."""
    box = screen.Element(name="Поиск", role="edit", left=10, top=40, right=300, bottom=76)
    rows = (_row("третий", 320), _row("первый", 120), _row("второй", 220))
    assert [item.name for item in outbox.results_zone(box, rows)] == ["первый", "второй", "третий"]


def test_results_zone_without_search_box_keeps_everything() -> None:
    """Строку поиска найти не удалось — лучше весь список, чем пустая выдача."""
    rows = (_row("Владимир", 900, left=620, right=1500),)
    assert len(outbox.results_zone(None, rows)) == 1


def test_results_zone_falls_back_when_column_is_empty() -> None:
    """Колонка посчиталась неверно — отдаём всё, что есть, вместо «никого не нашла»."""
    box = screen.Element(name="Поиск", role="edit", left=10, top=40, right=300, bottom=76)
    rows = (_row("Владимир", 10, left=620, right=1500),)
    assert len(outbox.results_zone(box, rows)) == 1


# ---------------------------------------------------------------- варианты запроса


def test_search_variants_try_stem_first() -> None:
    assert outbox.search_variants("Владимиру")[0].startswith("владимир")


def test_search_variants_add_first_word_for_two_part_names() -> None:
    """«Максим Петров» подписан просто «Максим» — последний заход ищет по одному имени."""
    variants = outbox.search_variants("Максим Петров")
    assert variants[0] == "макс петров"
    assert variants[-1] == "макс"


def test_search_variants_keep_handle_as_is() -> None:
    assert outbox.search_variants("@sanya_dev") == ("@sanya_dev",)


def test_search_variants_have_no_repeats() -> None:
    variants = outbox.search_variants("Лёша")
    assert len(variants) == len(set(variants))
