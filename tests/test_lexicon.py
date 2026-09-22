"""Словарь исправлений расслышанных слов.

Здесь закреплены два реальных бага, из-за которых команды молча не срабатывали:
«найди» превращалось в «юнити» (имя установленной программы), а «дела» — в
«сделай». Оба ломали не только само слово, но и всю команду следом.
"""

from __future__ import annotations

from core import lexicon


def test_trigger_word_survives_installed_app_names() -> None:
    """«найди» не должно притягиваться к ярлыку Unity из словаря программ."""
    lexicon.teach(["юнити", "unity"])
    assert lexicon.correct("найди картинку котов") == "найди картинку котов"


def test_free_text_after_trigger_is_untouched() -> None:
    lexicon.teach(["телеграм", "хром"])
    assert lexicon.correct("напиши маме хрома нет дома").endswith("хрома нет дома")


def test_casual_words_are_not_snapped_to_commands() -> None:
    """Обычная речь не должна превращаться в команды: порог 0.85, а не 0.8."""
    for word in ("дела", "устал", "привет", "хорошо", "нормально", "погода"):
        assert lexicon.correct_word(word) == word


def test_real_mishearings_are_still_fixed() -> None:
    assert lexicon.correct_word("скрыншот") == "скриншот"
    assert lexicon.correct_word("громкасть") == "громкость"


def test_correct_keeps_case_of_first_letter() -> None:
    assert lexicon.correct("Скрыншот экрана").startswith("Скриншот")


def test_sound_folds_unstressed_vowels() -> None:
    assert lexicon.sound("атлаз") == lexicon.sound("атлас")


def test_empty_input_is_safe() -> None:
    assert lexicon.correct("") == ""
    assert lexicon.correct("   ") == "   "
