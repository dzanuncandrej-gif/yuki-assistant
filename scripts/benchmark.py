"""Замер скорости и точности Юки по частям — без микрофона и без запуска окна.

    python scripts/benchmark.py            всё
    python scripts/benchmark.py --quick    без модели (только маршрутизация и речь)

Что меряется:
- маршрутизация: какая из ~40 типичных фраз уходит в нужный обработчик;
- распознавание речи: фраза, озвученная нейроголосом, → Whisper → текст и время;
- синтез: время до первого звука;
- модель: время до первого токена и скорость на коротких ответах.
Итог печатается таблицей и пишется в data/benchmark.json — так видно «до» и «после».
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# (фраза, где она должна оказаться). Маршруты — как в Assistant._respond_stream.
ROUTES: list[tuple[str, str]] = [
    ("который час", "time"),
    ("громкость 30", "volume_set"),
    ("открой телеграм", "open_app"),
    ("включи музыку Believer", "music"),
    ("включи мою любимую музыку", "playlist"),
    ("перемешай", "playlist"),
    ("следующий трек", "media_next"),
    ("пауза", "media_play"),
    ("выключи музыку", "media_stop"),
    ("какая погода на сегодня", "weather"),
    ("сделай скриншот", "screenshot"),
    ("напиши маме привет", "messenger_send"),
    ("доброе утро", "@briefing"),
    ("что мне писали", "@inbox"),
    ("кто мне писал сегодня", "@inbox"),
    ("что мне ему ответить", "@replies"),
    ("что за ошибка", "@codehelp"),
    ("почему у меня код не работает", "@codehelp"),
    ("напиши игру змейка", "@coder"),
    ("мне надо написать проект калькулятор создай папку на рабочем столе", "@coder"),
    ("добавь в калькулятор тёмную тему", "@change"),
    ("что скажешь об этом исполнителе", "@playing"),
    ("что сейчас играет", "@playing"),
    ("что у меня на экране", "@screen"),
    ("объясни подробно как работает интернет", "@deep"),
    ("давай созвонимся", "@call"),
]


def route_of(phrase: str) -> str:
    from core import briefing, codehelp, coding, commands, live, questions, replies
    from core.assistant import CALL_START

    if CALL_START.search(phrase):
        return "@call"
    if replies.wants_help(phrase):
        return "@replies"
    if codehelp.wants_help(phrase):
        return "@codehelp"
    if coding.wants_change(phrase, "Калькулятор"):
        return "@change"
    if coding.wants_code(phrase):
        return "@coder"
    if briefing.wants_briefing(phrase):
        return "@briefing"
    if briefing.wants_inbox(phrase):
        return "@inbox"
    if questions.about_playing(phrase):
        return "@playing"
    if live.asks_about_screen(phrase):
        return "@screen"
    intent = commands.match_intent(phrase)
    if intent:
        return intent
    if questions.deep_request(phrase):
        return "@deep"
    return "@agent"


def bench_routes() -> dict:
    rows, ok = [], 0
    for phrase, expected in ROUTES:
        got = route_of(phrase)
        ok += got == expected
        rows.append({"phrase": phrase, "expected": expected, "got": got})
    misses = [row for row in rows if row["got"] != row["expected"]]
    return {"total": len(rows), "ok": ok, "misses": misses}


def bench_speech() -> dict:
    """Нейроголос произносит фразы, Whisper их распознаёт: время и точность."""
    import asyncio
    import io

    import edge_tts
    import numpy as np

    from core import config, stt

    phrases = ["Юки, включи мою любимую музыку", "Напиши маме, что я буду через час",
               "Что у меня на экране?", "Сделай громкость тридцать процентов"]
    transcriber = stt.Transcriber(config.load()["stt"])
    results, synth_first = [], []
    for phrase in phrases:
        started = time.perf_counter()
        audio = bytearray()

        async def grab(text: str = phrase, started: float = started, audio: bytearray = audio) -> None:
            first = None
            async for chunk in edge_tts.Communicate(text, "ru-RU-DmitryNeural").stream():
                if chunk["type"] == "audio":
                    if first is None:
                        first = time.perf_counter() - started
                        synth_first.append(first)
                    audio.extend(chunk["data"])

        asyncio.run(grab())
        import soundfile as sf

        samples, rate = sf.read(io.BytesIO(bytes(audio)), dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        if rate != 16000:
            samples = np.interp(np.linspace(0, len(samples), int(len(samples) * 16000 / rate), endpoint=False),
                                np.arange(len(samples)), samples).astype(np.float32)
        began = time.perf_counter()
        text, _ = transcriber.transcribe(samples)
        results.append({"said": phrase, "heard": text, "ms": round((time.perf_counter() - began) * 1000)})
    return {"stt": results, "tts_first_audio_ms": [round(value * 1000) for value in synth_first]}


def bench_model() -> dict:
    from core import agent, config

    brain = agent.Agent(config.load()["brain"])
    brain.available()
    brain.warmup()
    rows = []
    for question in ("Привет! Как дела?", "Сколько будет 17 умножить на 23?", "Кто написал «Войну и мир»?",
                     "Посоветуй, что посмотреть вечером", "Переведи на английский: я люблю программировать"):
        started = time.perf_counter()
        first = None
        text = ""
        for piece in brain.quick_stream(question):
            first = first or time.perf_counter() - started
            text += piece
        total = time.perf_counter() - started
        rows.append({"q": question, "first_ms": round((first or total) * 1000), "total_ms": round(total * 1000),
                     "answer": text.strip()[:120]})
    return {"model": brain._model, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    report = {"at": time.strftime("%Y-%m-%d %H:%M"), "routes": bench_routes()}
    print(f"Маршрутизация: {report['routes']['ok']}/{report['routes']['total']}")
    for miss in report["routes"]["misses"]:
        print(f"   ✗ «{miss['phrase']}» → {miss['got']} (ждали {miss['expected']})")
    report["speech"] = bench_speech()
    for row in report["speech"]["stt"]:
        print(f"Распознавание {row['ms']:>5} мс: «{row['said']}» → «{row['heard']}»")
    print("Синтез, первый звук, мс:", report["speech"]["tts_first_audio_ms"])
    if not args.quick:
        report["model"] = bench_model()
        for row in report["model"]["rows"]:
            print(f"Модель {row['first_ms']:>5} мс до первого слова, {row['total_ms']:>5} мс всего: {row['q']}")
    out = ROOT / "data" / "benchmark.json"
    history = []
    if out.exists():
        try:
            history = json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            history = []
    history.append(report)
    out.write_text(json.dumps(history[-20:], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
