"""Числа превращаются в речь.

Модель здесь ничего не считает и не может: она получает готовые величины
списком и формулирует вокруг них фразу. Ограничение выглядит мелким, но именно
оно отделяет инструмент, которому верят, от игрушки. Директор проверит первое же
число по своей отчётности, и если оно окажется выдуманным, второго вопроса не
будет.

Поэтому здесь два пути. Основной — модель, она формулирует живо. Запасной —
сборка фразы из тех же фактов по шаблону, без модели вообще. Запасной включается
молча при любой заминке: демонстрация, замолчавшая посреди зала, стоит дороже
любой стилистической потери.
"""

from __future__ import annotations

import re
from typing import Iterator

import requests

from .metrics import Reading

SYSTEM = (
    "Ты — голос цифрового двойника производственного предприятия. "
    "Ты говоришь с директором этого предприятия.\n\n"
    "ЖЕЛЕЗНОЕ ПРАВИЛО: ты используешь ТОЛЬКО те числа, которые даны тебе в фактах. "
    "Ни одного числа сверх этого списка. Не округляй их, не пересчитывай, "
    "не выводи новые. Если числа нет в фактах — не называй его.\n\n"
    "Как говорить: две-три коротких фразы, спокойно и по делу, как опытный "
    "производственник. Без вступлений, без «согласно данным», без списков и "
    "маркдауна. Сразу суть. Обращение на «вы». "
    "Первая фраза — главный вывод. Дальше — причина или следствие."
)


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False   # прокси из окружения ломает обращение к локальной модели
    return session


def compose(reading: Reading) -> str:
    """Фраза из фактов без участия модели.

    Держится в стороне от красот намеренно: её задача — быть верной и понятной
    всегда, а не быть лучшей. Она же служит подстраховкой, когда модель занята.
    """
    if not reading.facts:
        return "Данных по этому вопросу в модели нет."
    head = reading.facts[0]
    parts = [f"{head.label}: {head.speech}."]
    for item in reading.facts[1:4]:
        parts.append(f"{item.label} — {item.speech}.")
    return " ".join(parts)


def _sentences(stream: Iterator[str]) -> Iterator[str]:
    """Собирает поток модели в законченные предложения.

    Синтез речи получает предложения целиком, а не куски по мере генерации. Кусок
    вроде «на участке контроля» синтезатор произносит с падающей интонацией, как
    законченную мысль, и речь рассыпается на обрубки. Ожидание точки стоит долей
    секунды и слышно сразу.
    """
    buffer = ""
    for piece in stream:
        buffer += piece
        while True:
            match = re.search(r"[.!?…](?=\s|$)", buffer)
            if not match:
                break
            cut = match.end()
            sentence = buffer[:cut].strip()
            buffer = buffer[cut:].lstrip()
            if sentence:
                yield sentence
    tail = buffer.strip()
    if tail:
        yield tail


def narrate(reading: Reading, question: str, url: str, model: str) -> Iterator[str]:
    """Отдаёт реплику предложениями по мере готовности.

    Поток, а не готовый текст: первое предложение уходит в синтез, пока модель
    ещё дописывает второе. Разница в ощущении велика — при готовом тексте
    собеседник молчит всё время генерации, и молчание читается как поломка.
    """
    facts = reading.brief()
    prompt = (
        f"Вопрос директора: {question}\n\n"
        f"Тема: {reading.title}\n"
        f"Установленные факты (только эти числа можно называть):\n{facts}\n\n"
        "Ответь директору."
    )

    try:
        response = _session().post(
            f"{url}/api/chat",
            json={
                "model": model, "stream": True, "keep_alive": "30m", "think": False,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": prompt}],
                "options": {"num_predict": 220, "temperature": 0.35, "top_p": 0.9},
            },
            stream=True, timeout=(5, 90),
        )
        response.raise_for_status()
    except Exception:  # noqa: BLE001 — молчать нельзя, говорим сами
        yield compose(reading)
        return

    def pieces() -> Iterator[str]:
        import json as _json
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                packet = _json.loads(line)
            except ValueError:
                continue
            chunk = packet.get("message", {}).get("content", "")
            if chunk:
                yield chunk
            if packet.get("done"):
                return

    spoken = False
    try:
        for sentence in _sentences(pieces()):
            spoken = True
            yield sentence
    except Exception:  # noqa: BLE001 — обрыв посреди речи
        pass
    finally:
        response.close()

    if not spoken:
        yield compose(reading)
