"""Проверка агента на живой модели: какие инструменты он выбирает на фразу.

Инструменты не выполняются — каждый вызов записывается и получает правдоподобный
успешный ответ. Так можно сравнивать модели и промпты, ничего не трогая в системе:

    python scripts/probe_agent.py                    модель из config.json
    python scripts/probe_agent.py qwen3:8b           другая модель
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import agent as agent_module
from core import config, tools
from core.tools import registry

PHRASES = (
    "открой телеграм и напиши Владимиру привет",
    "включи какую-нибудь спокойную музыку",
    "включи другую песню",
    "найди на ютубе обзор айфона 17",
    "включи видео как приготовить борщ",
    "открой браузер и найди рецепт пиццы",
    "сделай погромче и включи музыку",
    "кто такой Илон Маск",
    "сколько стоит биткоин сейчас",
    "что на экране",
    "закрой все окна кроме хрома",
    "создай на рабочем столе файл список покупок с текстом молоко хлеб",
    "поставь таймер на 5 минут",
    "какая погода завтра в Москве",
    "открой калькулятор",
    "привет, как ты?",
)


def main() -> int:
    cfg = config.load()
    brain = dict(cfg["brain"])
    if len(sys.argv) > 1:
        brain["model"] = sys.argv[1]
    calls: list[str] = []

    def fake_call(name, arguments=None, confirmed=False):
        calls.append(f"{name}({arguments})")
        if registry.get(name) is None:
            return registry.Result(False, f"инструмента «{name}» нет", name, arguments or {})
        return registry.Result(True, f"выполнено: {name}", name, arguments or {})

    tools.call = fake_call
    agent_module.tools.call = fake_call

    bot = agent_module.Agent({**brain, "owner": "Андрей"})
    if not bot.available(refresh=True):
        print("Ollama недоступна")
        return 1
    print("модель:", bot.model)
    bot.warmup()
    for phrase in PHRASES:
        calls.clear()
        bot.reset()
        started = time.monotonic()
        answer = "".join(bot.run_stream(phrase))
        print(f"\n» {phrase}  ({time.monotonic() - started:.1f} с)")
        for call in calls:
            print("    ·", call)
        print("  ←", answer.strip()[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
