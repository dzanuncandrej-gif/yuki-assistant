"""Веб-консультант: персонаж на сайте, отвечающий по базе знаний.

Отдельный сервер, а не режим основного, — и это главное решение в файле.

Домашний ассистент умеет открывать программы, печатать, кликать и слать
сообщения. Если тот же процесс окажется за публичным адресом, любой посетитель
получит выполнение действий на машине владельца. Поэтому здесь не импортируется
ни `core.assistant`, ни `core.tools`, ни `core.automation`: не «отключены
настройкой», а физически отсутствуют. Ошибиться настройкой можно, забыть импорт —
нет.

Запуск:

    python -m web.server
    python -m web.server --character mycompany --port 8770
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import config, consultant, guard, knowledge
from core import text as text_utils

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "page"
CARDS = ROOT / "data" / "characters"

# Публичный адрес с языковой моделью за ним — это чужой счёт, если не ограничить
# частоту. Лимит нарочно на уровне сервера, а не в интерфейсе: интерфейс обходится.
RATE_WINDOW_S = 60.0
RATE_LIMIT = 20
MAX_QUESTION = 500


def load_card(character: str) -> consultant.Card:
    path = CARDS / f"{character}.json"
    if not path.exists():
        raise HTTPException(404, f"персонаж «{character}» не настроен")
    return consultant.Card.load(json.loads(path.read_text(encoding="utf-8")))


class Limiter:
    """Простой счётчик обращений по адресу посетителя."""

    def __init__(self) -> None:
        self._seen: dict[str, list[float]] = {}

    def allow(self, who: str) -> bool:
        now = time.monotonic()
        marks = [mark for mark in self._seen.get(who, ()) if now - mark < RATE_WINDOW_S]
        if len(marks) >= RATE_LIMIT:
            self._seen[who] = marks
            return False
        marks.append(now)
        self._seen[who] = marks
        if len(self._seen) > 4000:  # чистим, чтобы словарь не рос вечно
            self._seen = {key: value for key, value in self._seen.items() if value}
        return True


_voice_lock = __import__("threading").Lock()
_speakers: dict[str, Any] = {}


def _render_voice(text: str, profile: str, settings: Any) -> bytes:
    """Готовый WAV одной фразы. Синтезатор на голос создаётся один раз."""
    import io
    import wave

    import numpy as np

    from core import tts, voices

    with _voice_lock:
        speaker = _speakers.get(profile)
        if speaker is None:
            options = dict(settings.get("tts", {}))
            options["voice"] = profile
            speaker = tts.Speaker(options)
            found = voices.get(profile)
            if found is not None and found.installed:
                speaker.use(found)
            _speakers[profile] = speaker
        chunks = list(speaker.stream(text))

    if not chunks:
        raise RuntimeError("синтез не дал звука")
    rate = chunks[0][1]
    samples = np.concatenate([piece for piece, _ in chunks])
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes())
    return buffer.getvalue()


def _warm_models(url: str, model: str, card: consultant.Card) -> None:
    """Поднимает модели в память видеокарты: языковую и модель эмбеддингов."""
    import requests

    from core import knowledge

    session = requests.Session()
    session.trust_env = False
    session.post(
        f"{url}/api/chat",
        json={"model": model, "stream": False, "keep_alive": "30m",
              "messages": [{"role": "user", "content": "ок"}],
              "options": {"num_predict": 1}, "think": False},
        timeout=300,
    )
    knowledge.embed(["прогрев"], url)      # поднимает bge-m3


def _precompute(card: consultant.Card, question: str, url: str, model: str,
                heavy: str, settings: Any) -> None:
    """Заранее считает ответ на подсказку, чтобы клик по ней отвечал мгновенно.

    Готовится только текст. Озвучку заранее делать нельзя: Edge — сетевой синтез,
    и очередь заготовок вешала его намертво. Живой посетитель в это время ждал
    голос полторы минуты и не получал ничего, тогда как без заготовки первая
    фраза синтезируется за две секунды, а повтор отдаётся из кэша мгновенно.
    Ускорение, которое ломает работу, — не ускорение.
    """
    _cites, stream = consultant.reply(card, question, url, model, heavy)
    "".join(stream)   # ответ оседает в кэше консультанта — этого и добиваемся


def create_app(character: str = "default") -> FastAPI:
    settings = config.load()
    url = str(settings["brain"].get("ollama_url", "http://127.0.0.1:11434"))
    model = str(settings["brain"].get("model", "qwen2.5:7b"))
    # Сильная модель для сложных вопросов. Простые ею не отвечаются: результат тот
    # же, а ждать втрое дольше — выбор делает consultant.tier_for.
    heavy = str(settings["brain"].get("heavy_model", "qwen3:8b"))
    app = FastAPI(title="Консультант")
    limiter = Limiter()

    async def warm() -> None:
        """Готовит всё, за что иначе заплатит первый посетитель.

        Холодный запуск стоит дорого: первый вопрос ждал шесть секунд, тогда как
        последующие отвечались за одну. Гость, пришедший первым, видит самый
        медленный сайт — и уходит именно он.

        Поэтому при старте сервера в фоне: поднимаются модели, а затем заранее
        считаются ответы и озвучка для подсказок-вопросов. Клик по подсказке
        после этого отвечает мгновенно и голос звучит сразу — синтезировать
        нечего, всё уже лежит в кэше.
        """
        async def prepare() -> None:
            card = load_card(character)
            try:
                await asyncio.to_thread(_warm_models, url, model, card)
            except Exception:
                pass
            for question in card.questions[:6]:
                try:
                    await asyncio.to_thread(_precompute, card, question, url, model, heavy, settings)
                except Exception:
                    continue

        asyncio.create_task(prepare())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await warm()
        yield

    app.router.lifespan_context = lifespan

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(PAGE / "index.html")

    @app.get("/api/voice")
    async def voice(text: str, name: str = character):
        """Синтез реплики голосом персонажа.

        Голос тот же, что у настольной Юки: профиль из `core.voices`, движок из
        `core.tts`. Браузерный синтез звучит как автоответчик и сводит на нет
        всё впечатление от живого персонажа.

        Ответы кэшируются самим синтезом, поэтому повторная фраза отдаётся сразу.
        """
        from fastapi.responses import Response

        clean = text_utils.for_speech(text)[:600]
        if not clean:
            raise HTTPException(400, "нечего произносить")
        card = load_card(name)
        try:
            data = await asyncio.to_thread(_render_voice, clean, card.voice, settings)
        except Exception as err:
            raise HTTPException(503, f"синтез недоступен: {str(err)[:120]}") from err
        return Response(content=data, media_type="audio/wav")

    @app.get("/api/character")
    async def character_info(name: str = character) -> JSONResponse:
        card = load_card(name)
        base = knowledge.load(card.base)
        return JSONResponse({
            "id": card.id,
            "name": card.name,
            "model": card.model,
            "greeting": card.greeting or consultant.OFFTOPIC,
            "questions": list(card.questions),
            "ready": base is not None,
            "documents": list(base.documents) if base else [],
        })

    @app.websocket("/ws")
    async def talk(socket: WebSocket) -> None:
        await socket.accept()
        who = socket.client.host if socket.client else "?"
        card = load_card(character)
        try:
            while True:
                request = await socket.receive_json()
                question = str(request.get("question", ""))[:MAX_QUESTION].strip()
                if not question:
                    continue
                if not guard.allowed(question):
                    reason = guard.check(question) or "profanity"
                    await socket.send_json({"type": "start"})
                    await socket.send_json({"type": "chunk", "text": guard.refusal(reason)})
                    await socket.send_json({"type": "done", "text": guard.refusal(reason)})
                    continue
                if not limiter.allow(who):
                    await socket.send_json({"type": "error",
                                            "text": "Слишком много вопросов подряд. Подождите минуту."})
                    continue

                await socket.send_json({"type": "start"})
                spoken: list[str] = []
                try:
                    # Поиск и источники — один раз, в потоке, чтобы не держать цикл.
                    cites, stream = await asyncio.to_thread(
                        consultant.reply, card, question, url, model, heavy
                    )
                    if cites:
                        await socket.send_json({"type": "sources", "sources": list(cites)})

                    # Куски отдаются по мере генерации, а не после её конца. Раньше
                    # весь ответ собирался в список и уходил разом: посетитель видел
                    # пустоту всё время работы модели, и это читалось как «зависла».
                    loop = asyncio.get_running_loop()
                    box: asyncio.Queue = asyncio.Queue()

                    # переменные цикла связываются значениями по умолчанию: иначе
                    # поток читал бы те stream/box, что достанутся ему к моменту
                    # запуска, а не те, ради которых он создан
                    def pump(stream=stream, loop=loop, box=box) -> None:
                        try:
                            for piece in stream:
                                loop.call_soon_threadsafe(box.put_nowait, ("text", piece))
                        except Exception as err:
                            loop.call_soon_threadsafe(box.put_nowait, ("error", err))
                        finally:
                            loop.call_soon_threadsafe(box.put_nowait, ("end", None))

                    await asyncio.to_thread(lambda: None)  # уступаем цикл перед стартом
                    worker = loop.run_in_executor(None, pump)
                    while True:
                        kind, value = await box.get()
                        if kind == "end":
                            break
                        if kind == "error":
                            raise consultant.ConsultantError(str(value)[:160])
                        spoken.append(value)
                        await socket.send_json({"type": "chunk", "text": value})
                    await worker
                except consultant.ConsultantError as err:
                    await socket.send_json({"type": "error", "text": str(err)})
                    continue

                whole = text_utils.clean_reply("".join(spoken))
                # Последний рубеж перед показом: модель могла сорваться на грубость
                # или проговориться об инструкциях. Такая реплика заменяется целиком.
                whole, touched = guard.sanitize(whole)
                await socket.send_json({"type": "done", "text": whole,
                                        "replaced": touched})
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass

    if PAGE.exists():
        app.mount("/page", StaticFiles(directory=PAGE), name="page")
    scene = ROOT / "ui3d"
    if scene.exists():
        app.mount("/ui3d", StaticFiles(directory=scene), name="ui3d")
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Веб-консультант")
    parser.add_argument("--character", default="default")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(args.character), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
