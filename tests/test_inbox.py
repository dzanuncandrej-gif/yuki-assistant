import datetime as dt

import pytest

from core import briefing, inbox

TODAY = dt.date(2026, 10, 2)


def parse(label: str) -> inbox.Chat:
    chat = inbox.parse(label, today=TODAY)
    assert chat is not None
    return chat


def test_group_message_from_someone_else_is_incoming_today():
    chat = parse("Группа, 8В, Стич 🙄💅: вела, Получено, в 20:42")
    assert (chat.kind, chat.name, chat.message, chat.incoming, chat.clock, chat.days_ago) == (
        "группа", "8В", "Стич 🙄💅: вела", True, "20:42", 0)


def test_own_last_message_is_not_incoming():
    assert parse("Ростык, Не просмотрено, Хуйня, в 21:14").incoming is False
    assert parse("Чебурек, С Premium, В сети, Закреплено, Просмотрено, 😛, 29.09.2026 в 17:03").incoming is False


def test_flags_and_trailing_reactions_are_not_part_of_message():
    chat = parse("Лёша, Закреплено, Привет Андрюха 🤝 спасибо большое 🤗, Реакции: ❤‍🔥, Получено, 02.08.2026 в 21:12")
    assert chat.message == "Привет Андрюха 🤝 спасибо большое 🤗"
    assert chat.days_ago == 61


def test_message_keeps_its_own_commas():
    chat = parse("Бот, BotFather, Верифицированный аккаунт, Done! Congratulations, you did it, Получено, вчера в 23:59")
    assert chat.kind == "бот"
    assert chat.message == "Done! Congratulations, you did it"
    assert chat.days_ago == 1


@pytest.mark.parametrize("label", [
    "Все чаты (4 непрочитанных чата)",
    "ㅤㅤㅤ ㅤ",
    "Избранное, cruror, С Premium, Закреплено, Фотография, Получено, 27.09.2026 в 17:16",
])
def test_non_chats_are_skipped(label):
    assert inbox.parse(label, today=TODAY) is None


def test_digest_lists_recent_incoming_and_skips_old():
    chats = (
        parse("Мама, Когда будешь дома?, Получено, в 18:00"),
        parse("Лёша, Привет, Получено, 02.08.2026 в 21:12"),
        parse("Канал, Новости, Пост, Получено, в 10:00"),
    )
    text = inbox.digest(chats, unread=2)
    assert "Мама" in text and "Когда будешь дома?" in text
    assert "Лёша" not in text
    assert "Каналы с новыми постами: Новости" in text


@pytest.mark.parametrize("phrase, inbox_intent, briefing_intent", [
    ("что мне писали", True, False),
    ("кто мне писал сегодня", True, False),
    ("есть новые сообщения?", True, False),
    ("проверь телеграм", True, False),
    ("доброе утро", False, True),
    ("юки, доброе утро", False, True),
    ("что у меня сегодня", False, True),
    ("напиши маме доброе утро", False, False),
    ("что мне ему ответить", False, False),
])
def test_intents(phrase, inbox_intent, briefing_intent):
    assert briefing.wants_inbox(phrase) is inbox_intent
    assert briefing.wants_briefing(phrase) is briefing_intent
