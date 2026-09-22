"""Локальный веб-сервер: раздаёт UI и стримит состояния ассистента по websocket."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import bus
from .assistant import Assistant

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def create_app(cfg: Mapping[str, Any]) -> FastAPI:
    assistant = Assistant(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bus.attach_loop(asyncio.get_running_loop())
        assistant.start()
        try:
            yield
        finally:
            assistant.stop()

    host = str(cfg.get("server", {}).get("host", "127.0.0.1"))
    port = int(cfg.get("server", {}).get("port", 8765))
    allowed_origins = {f"http://{h}:{port}" for h in (host, "127.0.0.1", "localhost")}

    app = FastAPI(title="Юки", lifespan=lifespan)
    app.state.assistant = assistant

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        # Браузерная страница с другого источника не должна дотягиваться до
        # ассистента через WebSocket — сервер слушает только localhost, но без
        # этой проверки любая открытая в браузере вкладка могла бы подключиться
        # и слать команды от имени пользователя (см. заголовок Origin в запросе).
        origin = socket.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            await socket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await socket.accept()
        queue = bus.bus.subscribe()
        for event in bus.bus.history():
            await socket.send_json(event)
        await socket.send_json(bus.bus.snapshot())
        pump = asyncio.create_task(_pump(socket, queue))
        try:
            while True:
                message = await socket.receive_json()
                await _handle_client_message(assistant, message)
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            pump.cancel()
            bus.bus.unsubscribe(queue)

    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")
    return app


async def _pump(socket: WebSocket, queue: asyncio.Queue) -> None:
    try:
        while True:
            event = await queue.get()
            await socket.send_json(event)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        return


async def _handle_client_message(assistant: Assistant, message: Mapping[str, Any]) -> None:
    action = str(message.get("action", ""))
    if action == "text":
        text = str(message.get("text", ""))
        await asyncio.to_thread(assistant.handle_text, text)
    elif action == "mute":
        assistant.set_muted(bool(message.get("value", True)))
    elif action == "ping":
        bus.bus.publish(bus.bus.snapshot())
