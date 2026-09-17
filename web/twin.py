"""Сервер цифрового двойника предприятия.

Отдельный процесс от домашнего ассистента — по той же причине, что и веб-консультант.
Ассистент умеет открывать программы, печатать и кликать на машине владельца; всё,
что окажется за публичным адресом, рано или поздно получит запрос от постороннего.
Поэтому здесь нет ни `core.assistant`, ни `core.automation`, ни `core.tools`: не
выключены настройкой, а не импортированы вовсе. Настройку можно перепутать,
отсутствующий импорт — нет.

Запуск:

    python -m web.twin
    python -m web.twin --port 8771
"""

from __future__ import annotations

import argparse
import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core import config, guard
from core import text as text_utils
from core.twin import PLANT, Scenario
from core.twin import intent as routing
from core.twin import metrics, narrate

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "page"

RATE_WINDOW_S = 60.0
RATE_LIMIT = 40
MAX_QUESTION = 400


# --------------------------------------------------------------------------- #
# Голос
# --------------------------------------------------------------------------- #
#
# Синтез здесь свой, а не общий с веб-консультантом, и держится на Piper вместо
# заданного в настройках Edge. Причина измерена: Edge — сетевой сервис, и на тех
# же фразах он давал от трёх с половиной до десяти с половиной секунд, тогда как
# Piper укладывается в ноль целых полторы десятых. Разброс хуже самой задержки:
# речь, которая иногда начинается через десять секунд, воспринимается как
# поломка, и никакая сцена этого уже не вытягивает.
#
# Настройки предприятия при этом не трогаются: настольная Юки продолжает
# говорить через Edge, как и настроена.

_voice_lock = __import__("threading").Lock()
_speaker: Any = None
_heard: dict[str, bytes] = {}


def _render_voice(text: str, profile: str, settings: Any) -> bytes:
    """WAV одной фразы. Синтезатор создаётся один раз, готовое запоминается."""
    import io
    import wave

    import numpy as np

    from core import tts, voices

    key = f"{profile}|{text}"
    found = _heard.get(key)
    if found is not None:
        return found

    global _speaker
    with _voice_lock:
        if _speaker is None:
            options = dict(settings.get("tts", {}))
            options["engine"] = "piper"
            options["voice"] = profile
            speaker = tts.Speaker(options)
            known = voices.get(profile)
            if known is not None and getattr(known, "installed", False):
                speaker.use(known)
            _speaker = speaker
        chunks = list(_speaker.stream(text))

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
    data = buffer.getvalue()

    # Кэш ограничен: одни и те же формулировки повторяются постоянно, но расти
    # бесконечно ему незачем — это демонстрация, а не хранилище.
    if len(_heard) > 400:
        _heard.clear()
    _heard[key] = data
    return data


# --------------------------------------------------------------------------- #
# Сериализация состояния для сцены
# --------------------------------------------------------------------------- #

def _stations(plant, result) -> list[dict]:
    """Участки с их живыми числами — то, чем сцена красит и двигает.

    Очередь отдаётся и средняя, и пиковая. Средняя честнее описывает положение
    дел, но рисовать по ней нельзя: куча перед контролем в двести пятьдесят
    заказов и куча в четыреста выглядят одинаково, если не знать масштаба.
    """
    out = []
    for station in plant.stations:
        stat = result.station(station.id)
        out.append({
            "id": station.id,
            "name": station.name,
            "role": station.role,
            "staff": station.staff,
            "position": list(station.position),
            "load": round(stat["load"], 4),
            "queue": round(stat["queue_avg"], 1),
            "peak": stat["queue_peak"],
            "wait_days": round(stat["wait_days"], 3),
            "throughput": round(stat["throughput_day"], 2),
            "defect": station.defect,
            "rework_to": station.rework_to,
        })
    return out


def _state(plant) -> dict:
    """Полное состояние предприятия для сцены и приборной панели."""
    result = metrics.simulate(plant)
    neck = result.bottleneck
    return {
        "name": plant.name,
        "orders_day": plant.orders_day,
        "order_value": plant.order_value,
        "stations": _stations(plant, result),
        "bottleneck": neck["id"],
        "lead_days": round(result.lead_days, 2),
        "lead_p95_days": round(result.lead_p95_days, 2),
        "late_share": round(result.late_share, 4),
        "wip": result.wip_end,
        "completed_day": round(result.completed / max(result.days, 1), 2),
        "revenue_month": round(result.revenue_month),
        "penalty_month": round(result.penalty_month),
        "payroll_month": round(result.payroll_month),
        "monthly": list(result.monthly),
        "money": {
            "revenue": metrics.money(result.revenue_month),
            "penalty": metrics.money(result.penalty_month),
            "payroll": metrics.money(plant.payroll_month),
        },
    }


def _reading(reading: metrics.Reading) -> dict:
    return {
        "metric": reading.metric,
        "title": reading.title,
        "focus": reading.focus,
        "camera": reading.camera,
        "chart": reading.chart,
        "series": list(reading.series),
        "facts": [
            {"key": item.key, "label": item.label, "value": item.display, "accent": item.accent}
            for item in reading.facts
        ],
    }


def _scenario(payload: dict) -> Scenario:
    """Сценарий из запроса. Всё чужое приводится к своим типам и границам.

    Данные приходят из браузера, а значит могут быть любыми. Ограничения тут не
    от недоверия к интерфейсу, а потому что запрос до сервера доходит и мимо него.
    """
    known = {station.id for station in PLANT.stations}
    staff = {key: max(-6, min(12, int(value)))
             for key, value in dict(payload.get("staff") or {}).items() if key in known}
    speed = {key: max(0.2, min(2.5, float(value)))
             for key, value in dict(payload.get("speed") or {}).items() if key in known}
    defect = {key: max(0.0, min(0.6, float(value)))
              for key, value in dict(payload.get("defect") or {}).items() if key in known}
    demand = max(0.3, min(3.0, float(payload.get("demand") or 1.0)))
    return Scenario(staff=staff, speed=speed, defect=defect, demand=demand)


class Limiter:
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
        if len(self._seen) > 4000:
            self._seen = {key: value for key, value in self._seen.items() if value}
        return True


def create_app() -> FastAPI:
    settings = config.load()
    url = str(settings["brain"].get("ollama_url", "http://127.0.0.1:11434"))
    talk = str(settings["brain"].get("model", "qwen2.5:7b"))
    fast = "qwen2.5:3b"      # только для разбора непонятой фразы: решение из одного слова
    voice_profile = "samurai"

    app = FastAPI(title="Цифровой двойник")
    limiter = Limiter()

    async def warm() -> None:
        """Готовит всё, за что иначе заплатит первый вопрос.

        Холодный прогон года, холодная языковая модель и холодный синтез вместе
        дают около десяти секунд на первом вопросе — ровно в тот момент, когда на
        экран смотрят внимательнее всего. Поэтому базовый прогон, перебор ходов и
        обе модели поднимаются заранее, ещё до того, как страница открыта.
        """
        async def prepare() -> None:
            try:
                await asyncio.to_thread(metrics.simulate, PLANT)
                await asyncio.to_thread(metrics.best_move, PLANT)
                await asyncio.to_thread(metrics.bottleneck, PLANT)
            except Exception:  # noqa: BLE001 — прогрев не обязан удаться
                pass
            try:
                import requests
                session = requests.Session()
                session.trust_env = False
                for model in (talk, fast):
                    session.post(f"{url}/api/chat", json={
                        "model": model, "stream": False, "keep_alive": "30m", "think": False,
                        "messages": [{"role": "user", "content": "ок"}],
                        "options": {"num_predict": 1},
                    }, timeout=300)
            except Exception:  # noqa: BLE001
                pass
            try:
                # Первый синтез поднимает модель Piper и стоит около двух с
                # половиной секунд — ровно один раз и заранее, а не при госте.
                await asyncio.to_thread(_render_voice, "Предприятие на связи.",
                                        voice_profile, settings)
            except Exception:  # noqa: BLE001
                pass

        asyncio.create_task(prepare())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # noqa: ANN202
        await warm()
        yield

    app.router.lifespan_context = lifespan

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(PAGE / "twin.html")

    @app.get("/api/twin/plant")
    async def plant_state() -> JSONResponse:
        return JSONResponse(await asyncio.to_thread(_state, PLANT))

    @app.post("/api/twin/scenario")
    async def scenario(payload: dict) -> JSONResponse:
        """Считает сценарий и возвращает и разбор, и новое состояние сцены.

        Одним ответом, а не двумя запросами: приборная панель и трёхмерная сцена
        обязаны показывать одно и то же. Разъехавшись даже на кадр, они выдают,
        что показывают не предприятие, а две отдельные картинки.
        """
        request = _scenario(payload or {})
        if request.empty:
            return JSONResponse({"reading": None, "state": await asyncio.to_thread(_state, PLANT)})
        reading = await asyncio.to_thread(metrics.compare, PLANT, request)
        state = await asyncio.to_thread(_state, PLANT.with_scenario(request))
        return JSONResponse({"reading": _reading(reading), "state": state,
                             "describe": request.describe(PLANT)})

    @app.get("/api/twin/station/{station_id}")
    async def station(station_id: str) -> JSONResponse:
        try:
            reading = await asyncio.to_thread(metrics.station_detail, PLANT, station_id)
        except KeyError as err:
            raise HTTPException(404, "нет такого участка") from err
        return JSONResponse(_reading(reading))

    @app.get("/api/twin/voice")
    async def voice(text: str):
        """Синтез реплики голосом двойника.

        Тот же движок и профиль, что у настольной Юки. Браузерный синтез звучит
        как автоответчик, и после него никакая трёхмерная сцена уже не спасает
        впечатление: голос — единственное здесь, что читается как присутствие.
        """
        clean = text_utils.for_speech(text)[:600]
        if not clean:
            raise HTTPException(400, "нечего произносить")
        try:
            data = await asyncio.to_thread(_render_voice, clean, voice_profile, settings)
        except Exception as err:  # noqa: BLE001 — без голоса сцена работает дальше
            raise HTTPException(503, f"синтез недоступен: {str(err)[:120]}") from err
        return Response(content=data, media_type="audio/wav")

    @app.websocket("/twin/ws")
    async def talk_socket(socket: WebSocket) -> None:
        """Разговор с предприятием.

        Порядок отправки здесь и есть ощущение мгновенности. Сначала уходят числа
        и участок, на который смотреть, — камера трогается и цифры появляются
        через доли секунды. Речь идёт следом, предложение за предложением. Если
        ждать готовой реплики и отправлять всё разом, ответ придёт тот же, а
        разговор развалится: собеседник будет молчать несколько секунд и потом
        выкладывать всё сразу.
        """
        await socket.accept()
        who = socket.client.host if socket.client else "?"
        try:
            while True:
                request = await socket.receive_json()
                question = str(request.get("question", ""))[:MAX_QUESTION].strip()
                if not question:
                    continue
                if not limiter.allow(who):
                    await socket.send_json({"type": "error",
                                            "text": "Слишком много вопросов подряд. Подождите минуту."})
                    continue
                if not guard.allowed(question):
                    await socket.send_json({"type": "error",
                                            "text": guard.refusal(guard.check(question) or "profanity")})
                    continue

                await socket.send_json({"type": "start", "question": question})

                want = await asyncio.to_thread(routing.resolve, question, url, fast)
                reading = await asyncio.to_thread(routing.read, PLANT, want)
                await socket.send_json({"type": "reading", **_reading(reading)})

                # Если вопрос был сценарием, сцена должна перестроиться под него.
                if reading.scenario is not None:
                    state = await asyncio.to_thread(_state, PLANT.with_scenario(reading.scenario))
                    await socket.send_json({"type": "state", "state": state,
                                            "describe": reading.scenario.describe(PLANT)})

                loop = asyncio.get_running_loop()
                box: asyncio.Queue = asyncio.Queue()

                def pump() -> None:
                    try:
                        for sentence in narrate.narrate(reading, question, url, talk):
                            loop.call_soon_threadsafe(box.put_nowait, ("say", sentence))
                    except Exception as err:  # noqa: BLE001
                        loop.call_soon_threadsafe(box.put_nowait, ("fail", str(err)[:160]))
                    finally:
                        loop.call_soon_threadsafe(box.put_nowait, ("end", None))

                worker = loop.run_in_executor(None, pump)
                spoken: list[str] = []
                while True:
                    kind, value = await box.get()
                    if kind == "end":
                        break
                    if kind == "fail":
                        # Молчать нельзя: реплика собирается из тех же фактов.
                        value = narrate.compose(reading)
                        kind = "say"
                    clean, _ = guard.sanitize(str(value))
                    spoken.append(clean)
                    await socket.send_json({"type": "say", "text": clean})
                await worker
                await socket.send_json({"type": "done", "text": " ".join(spoken)})
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass

    if PAGE.exists():
        app.mount("/page", StaticFiles(directory=PAGE), name="page")
    scene = ROOT / "ui3d"
    if scene.exists():
        app.mount("/ui3d", StaticFiles(directory=scene), name="ui3d")
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Цифровой двойник предприятия")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
