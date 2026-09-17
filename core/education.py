"""Учебный режим: разбор школьных заданий с решением по шагам.

Обычный ответ ассистента короткий — он читается вслух. Учебная задача требует другого:
условие, формула, вычисления, проверка, ответ. Поэтому здесь свой промпт, свои лимиты
и своя проверка арифметики: числовые выражения пересчитываются на месте, чтобы модель
не «ошиблась в столбик».

Задание может прийти текстом, с фотографии, со скриншота или с камеры — картинку
сначала читает модель зрения, потом решает языковая.
"""

from __future__ import annotations

import ast
import operator
import re

SUBJECTS = {
    "математика": ("алгебр", "геометр", "уравнен", "неравенств", "функци", "интеграл", "производн",
                   "треугольник", "окружност", "вычисли", "упрости", "реши", "дробь", "процент"),
    "физика": ("физик", "скорост", "ускорен", "сила", "энерги", "мощност", "напряжен", "ток",
               "сопротивлен", "давлен", "масса", "импульс", "джоул", "ньютон"),
    "химия": ("хими", "реакци", "молекул", "вещество", "раствор", "моль", "валентност", "оксид",
              "кислот", "щёлоч", "уравнение реакции"),
    "биология": ("биолог", "клетк", "организм", "фотосинтез", "ген", "днк", "белок", "экосистем"),
    "русский язык": ("русск", "морфем", "орфограф", "пунктуац", "часть речи", "разбор слова",
                     "синтаксическ", "запят", "склонен", "спряжен"),
    "литература": ("литератур", "стихотворен", "поэт", "роман", "образ героя", "анализ произведен"),
    "история": ("истори", "век", "война", "битв", "сражен", "революц", "реформ", "княз",
                "император", "царь", "договор", "в каком году"),
    "география": ("географ", "материк", "климат", "население", "рельеф", "часовой пояс", "карта"),
    "информатика": ("информатик", "алгоритм", "программ", "код", "питон", "python", "паскаль",
                    "система счислен", "логическ", "бит", "байт"),
    "английский": ("english", "английск", "translate", "перевед", "tense", "present perfect"),
    "обществознание": ("обществознан", "право", "экономик", "конституц", "гражданин", "рынок"),
}

SOLVER_PROMPT = """Ты — терпеливый школьный преподаватель, который объясняет так, чтобы ученик понял и смог решить сам.

Разбери задание по этой схеме:
1. «Дано» — что известно, с обозначениями и единицами.
2. «Что найти».
3. «Решение» — по шагам. Каждый шаг: что делаем и почему. Формулу сначала записываешь в общем виде, потом подставляешь числа.
4. «Проверка» — если можно проверить (подстановкой, прикидкой, размерностью) — проверь.
5. «Ответ» — отдельной строкой, коротко и точно, с единицами измерения.

Правила:
- Считай аккуратно и показывай промежуточные вычисления, а не только итог.
- Если в условии не хватает данных — скажи, чего не хватает, и реши в общем виде.
- Если задание с вариантами ответа — назови верный и объясни, почему остальные не подходят.
- Пиши по-русски, простым языком, без markdown-разметки со звёздочками. Формулы записывай обычным текстом.
- Не выдумывай факты. Если это история или биология и ты не уверен — так и скажи."""

VISION_PROMPT = (
    "Перепиши текстом всё, что видно на этом изображении: условие задачи, числа, формулы, "
    "варианты ответов, подписи к рисунку. Ничего не решай и не сокращай — только точная "
    "расшифровка. Если есть чертёж или график, опиши его словами."
)

# сколько символов ответа не озвучиваем, а только показываем
SPEECH_DIGEST = 400

_MATH = re.compile(r"^[\d\s+\-*/().,^%]+$")
_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv,
}


def detect_subject(text: str) -> str:
    """Предмет по ключевым словам — он идёт в промпт и помогает модели держать контекст.

    Слова ищутся с начала слова: иначе «бит» находился внутри «битвы», и Куликовская
    битва становилась информатикой.
    """
    lowered = str(text or "").lower()
    best, score = "", 0
    for subject, markers in SUBJECTS.items():
        hits = sum(1 for marker in markers if re.search(rf"\b{re.escape(marker)}", lowered))
        if hits > score:
            best, score = subject, hits
    return best


_MARKDOWN = re.compile(r"\*{1,3}|`{1,3}|^#{1,6}\s*", re.MULTILINE)
_LATEX_WRAP = re.compile(r"\$\$?")
_LATEX_CMD = re.compile(r"\\(?:text|mathrm|mathbf|frac|quad|qquad)\b\s*|\\(?:cdot|times|approx)|\\[,;!]")


def clean_solution(text: str) -> str:
    """Убирает markdown и LaTeX: решение читают глазами и вслух, а не в редакторе формул."""
    clean = _MARKDOWN.sub("", str(text or ""))
    clean = _LATEX_WRAP.sub("", clean)
    clean = _LATEX_CMD.sub(
        lambda match: {"\\cdot": " · ", "\\times": " × ", "\\approx": " ≈ "}.get(match.group(0).strip(), " "),
        clean,
    )
    clean = clean.replace("\\", "").replace("{", "").replace("}", "")
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    return re.sub(r"\n{3,}", "\n\n", clean).strip()


def looks_like_task(text: str) -> bool:
    """Похоже ли на школьное задание, а не на обычную просьбу."""
    lowered = str(text or "").lower()
    triggers = (
        "реши", "решить", "задач", "пример", "вычисли", "упрости", "докажи", "найди значение",
        "уравнени", "объясни тему", "разбери", "домашк", "домашнее задание", "упражнени",
        "контрольн", "как решать", "помоги с",
    )
    return any(trigger in lowered for trigger in triggers)


def calculate(expression: str) -> float | None:
    """Считает числовое выражение без eval: нужна проверка арифметики модели."""
    clean = expression.replace("^", "**").replace(",", ".").strip()
    if not clean or not _MATH.match(expression.replace("^", "").strip()):
        return None
    try:
        return _evaluate(ast.parse(clean, mode="eval").body)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, KeyError, OverflowError):
        return None


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_evaluate(node.operand))
    raise ValueError("недопустимое выражение")


def verify_arithmetic(solution: str, limit: int = 12) -> str:
    """Ищет в решении равенства вида «2 + 3 * 4 = 14» и пересчитывает их.

    Языковые модели ошибаются в устном счёте чаще, чем в рассуждении. Пересчёт стоит
    доли миллисекунды и ловит именно те ошибки, из-за которых верное решение даёт
    неверный ответ.
    """
    problems: list[str] = []
    for left, right in re.findall(r"([\d\s+\-*/().,^]{3,40})=\s*(-?[\d.,]+)", solution)[:limit]:
        value = calculate(left)
        if value is None:
            continue
        try:
            expected = float(right.replace(",", "."))
        except ValueError:
            continue
        if abs(value - expected) > max(0.01, abs(value) * 0.001):
            problems.append(f"{left.strip()} = {value:g}, а не {expected:g}")
    if not problems:
        return ""
    return "Проверка вычислений: " + "; ".join(problems)


def build_prompt(task: str, subject: str = "", grade: str = "") -> str:
    """Собирает задание для модели вместе с подсказкой о предмете и классе."""
    parts = [SOLVER_PROMPT]
    detected = subject or detect_subject(task)
    if detected:
        parts.append(f"Предмет: {detected}.")
    if grade:
        parts.append(f"Класс: {grade}.")
    parts.append(f"Задание:\n{task.strip()}")
    return "\n\n".join(parts)


def speech_digest(solution: str) -> str:
    """Что сказать вслух: ответ и суть, а не всё решение целиком."""
    text = clean_solution(solution)
    if not text:
        return "Не смог разобрать задание."
    match = re.search(r"ответ\s*[:—-]?\s*(.+)", text, re.IGNORECASE)
    if match:
        answer = match.group(1).strip().split("\n")[0]
        return f"Ответ: {answer}. Полное решение показал на экране."
    return text[:SPEECH_DIGEST] + ("…" if len(text) > SPEECH_DIGEST else "")
