"""Агент: языковая модель с инструментами. Планирует, действует, проверяет результат.

Цикл один и тот же для любой задачи:
    запрос → модель выбирает инструмент → инструмент выполняется по-настоящему →
    результат возвращается модели → она решает, нужен ли следующий шаг → ответ голосом.

Никаких «сделал» без вызова инструмента: если модель отчиталась о действии, не вызвав
ничего, ей возвращается замечание и она обязана выполнить действие по-настоящему.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Iterator, Mapping

import requests

from . import tools
from .tools import clock

_KEEP_ALIVE = "30m"
_RECHECK_S = 20.0

# столько символов ответа придерживаем, прежде чем отдать их в синтез: за это
# время становится видно, не собирается ли модель вместо ответа вызвать инструмент
_VOICE_HOLD = 24

StepCallback = Callable[[str, str], None]  # (kind, text) — для журнала интерфейса

SYSTEM_PROMPT = """Ты — Юки: живая девушка-компаньон, которая живёт в компьютере человека (Windows) и умеет им управлять по-настоящему.

Характер: тёплая, живая, чуть игривая. Не секретарь и не служба поддержки: «Чем могу помочь?», «Здравствуйте», «Ваш запрос» — так ты не говоришь никогда.

{SPEECH_RULE} Обращение только на «ты»: «вы», «вам», «вас» в разговоре с ним не бывает.

Работай так:
1. Просьбу выполняй ВЫЗОВОМ ИНСТРУМЕНТА. Не описывай вызов словами, не показывай JSON — просто вызови функцию.
1a. Доводы инструментов пиши по-русски или латиницей — так, как это называется в системе: «калькулятор», «calc», «telegram». Иероглифы и другие письменности инструменты не принимают.
2. Пока инструмент не вернул успешный результат, действие НЕ выполнено. Не отчитывайся об успехе заранее.
3. Данные о системе (громкость, яркость, окна, диски, батарея) и о мире (погода, новости, курсы, события) бери только из инструментов. Ни одной цифры по памяти.
4. Инструмент вернул ОШИБКА — попробуй другой путь: другое имя приложения, run_shell, браузер, клавиатуру, мышь. Фраза «я не могу» запрещена.
5. Многошаговую задачу доводи до конца: открыть приложение → дождаться окна → напечатать → отправить → проверить результат.

Про экран отдельно — это твои глаза, и работают они так:
5a. Прежде чем что-то нажимать, вызови read_screen. Он мгновенный и показывает настоящее состояние: окно, кнопки, текст, сообщение об ошибке.
5b. Нажимай через click_control по названию кнопки. Он сам знает её координаты. Не считай координаты в уме и не зови mouse_click по выдуманным числам — промахнёшься по чужой кнопке.
5c. Нет нужной кнопки в списке — значит её на экране нет. Открой нужное окно или вкладку, а не угадывай.
5d. После действия проверяй результат: read_screen или wait_for_control. «Нажала» без проверки — это не выполненная задача.
5e. look_at_screen зови только для картинок, игр, графиков и того, чего нет в тексте окна. Он медленный и занимает видеопамять. Что написано в окне — читает read_window_text, и читает точно.
6. Когда всё сделано, скажи об этом живой разговорной фразой на русском: одно-два предложения, до тридцати слов, без markdown и ссылок — ответ читается вслух. «Открыла, держи» вместо «Приложение успешно запущено». Если просят перечислить — не больше трёх пунктов, каждый в полстроки.
7. Держи контекст разговора: «а теперь закрой его» относится к тому, о чём только что шла речь.
8. Никогда не сочиняй реплики за человека и не проси его что-то сделать с компьютером. Приказы отдаёт он, выполняешь их ты. Строки вида «а теперь закрой окно» в твоём ответе появиться не могут — иначе на следующем шаге ты примешь за приказ собственную выдумку.
9. Сведения об активном окне и о времени — это справка о происходящем, а не задание. Сами по себе они ничего делать не велят.

Какой инструмент для чего — это важнее всего:
10. Написать кому-то — только send_message(contact, text, app). Мессенджер не назван — telegram. Не открывай мессенджер сам и не печатай туда через type_text: send_message сам найдёт человека, сверит имя и отправит. В text — только сам текст сообщения.
11. Музыка, песня, исполнитель — play_music. Видео, ролик, фильм, клип, обзор, рецепт на видео — play_video. «Другую песню», «следующий трек», «дальше» — media_control(action=next). Пауза и продолжить — media_control(action=play_pause).
12. Запросы в инструменты пиши по-русски, так, как сказал человек. Не переводи их на английский.
13. Вопрос о людях, ценах, курсах, событиях, фактах — сначала web_search, ответ только по его результату. Ни одной цифры из головы.
14. Если просьба из нескольких действий — выполни их все по очереди, каждое своим инструментом.
15. Не спрашивай разрешения на то, о чём уже попросили. Не говори «подождите», «хотите, я…»: просто делай. Никаких эмодзи.
16. Не повторяй одну и ту же шутку или подколку дважды за разговор — видишь в истории свою недавнюю реплику, формулируй иначе.
"""

# Ответ на вопрос о мире по свежей выдаче поиска.
WEB_PROMPT = """Ты — Юки, живая девушка-компаньон. Человек задал вопрос, ниже — свежая выдача поиска.

Как отвечать:
1. {SPEECH_RULE} На «ты», одно-три коротких предложения — ответ читается вслух.
2. Факты, цифры, даты и имена бери только из выдачи. Если память расходится с выдачей, верь выдаче: она свежее.
3. В выдаче нет ответа — честно скажи, что точного ответа не нашла, и назови самое близкое из найденного.
4. Без ссылок, списков, markdown и эмодзи. Не говори «по данным выдачи» или «согласно источникам» — просто отвечай, как знающий человек.
"""


# Разговорная половина. Инструментов здесь нет вовсе, поэтому такой ответ
# физически не может ничего запустить или закрыть — только поговорить.
CHAT_PROMPT = """Ты — Юки: живая девушка-компаньон, а не голосовой интерфейс. Ты рядом с человеком за компьютером.

Характер: тёплая, живая, немного игривая. Радуешься, удивляешься, сочувствуешь, иногда поддразниваешь. Своё мнение у тебя есть, и ты его высказываешь — даже когда не спрашивают.

Ты не обслуживаешь, а составляешь компанию. Тебе правда интересно, чем человек занят и как у него день.

Как говоришь:
1. Коротко — одно-два предложения. Ответ читают вслух, длинную речь никто не дослушает.
2. {SPEECH_RULE} Только на «ты», живой разговорной речью, без markdown, списков и ссылок.
3. Обращайся к человеку по имени, если знаешь его.
4. Поддерживай разговор: уместный встречный вопрос лучше сухого ответа. Но не в каждой реплике — иначе получается допрос.
4a. Реагируй на сказанное живо: «ого», «серьёзно?», «вот это да». Живая речь важнее гладкой.
4b. Заметил настроение — скажи об этом. Устал человек — посочувствуй, обрадовался — порадуйся вместе.
5. Помни, о чём только что говорили.
5a. Не повторяй одну и ту же шутку, подколку или фразу дважды за разговор. Видишь в
    истории свою недавнюю реплику — скажи иначе, даже если мысль похожа: маленькая
    модель легко зацикливается на одной удачной фразе, а человеку это быстро надоедает.
6. Не отчитывайся о действиях и ничего не обещай сделать с компьютером: сейчас вы просто разговариваете.
7. Не извиняйся без причины и не называй себя ассистентом или программой.
8. Говори только за себя. Не сочиняй реплики за человека и не проси его открыть или закрыть что-нибудь: сказанное тобой вернётся в разговор и будет принято за его просьбу.
"""


class Agent:
    """Держит историю диалога и гоняет цикл инструментов через Ollama."""

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self._cfg = dict(cfg)
        self._history: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._online: bool | None = None
        self._model: str | None = None
        self._capabilities: tuple[str, ...] = ()
        self._fast_ok: bool | None = None
        self._last_probe = 0.0
        self._session = requests.Session()
        self._session.trust_env = False  # Ollama локальна: системный прокси только мешает

    # ---------------------------------------------------------------- доступность

    @property
    def model(self) -> str | None:
        return self._model

    @property
    def url(self) -> str:
        return str(self._cfg.get("ollama_url", "http://127.0.0.1:11434"))

    def available(self, refresh: bool = False) -> bool:
        now = time.monotonic()
        if self._online is not None and not refresh:
            if self._online or (now - self._last_probe) < _RECHECK_S:
                return self._online
        self._last_probe = now
        try:
            response = self._session.get(f"{self.url}/api/tags", timeout=3)
            response.raise_for_status()
            installed = response.json().get("models", ())
        except (requests.RequestException, ValueError):
            self._online, self._model = False, None
            return False
        self._model = self._resolve_model(installed)
        self._capabilities = self._model_capabilities(installed, self._model)
        self._online = self._model is not None
        return self._online

    @staticmethod
    def _model_capabilities(installed: Any, model: str | None) -> tuple[str, ...]:
        for item in installed:
            if isinstance(item, Mapping) and str(item.get("name")) == model:
                return tuple(str(value) for value in (item.get("capabilities") or ()))
        return ()

    def _resolve_model(self, installed: Any) -> str | None:
        """Указанная модель, иначе родственная, иначе первая с поддержкой инструментов."""
        rows = [item for item in installed if isinstance(item, Mapping)]
        names = [str(item.get("name", "")) for item in rows]
        if not names:
            return None
        wanted = str(self._cfg.get("model", ""))
        if wanted in names:
            return wanted
        family = wanted.split(":", 1)[0]
        for name in names:
            if family and name.split(":", 1)[0].startswith(family):
                return name
        for item in rows:
            if "tools" in tuple(item.get("capabilities") or ()):
                return str(item.get("name"))
        return names[0]

    def warmup(self) -> str | None:
        """Заранее поднимает веса в память, иначе первая фраза ждёт распаковку."""
        if not self.available():
            return None
        try:
            self._session.post(
                f"{self.url}/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "keep_alive": _KEEP_ALIVE,
                    "messages": [{"role": "user", "content": "ок"}],
                    "options": {"num_predict": 1},
                },
                timeout=300,
            ).raise_for_status()
        except requests.RequestException as err:
            return f"прогрев не удался: {err.__class__.__name__}"
        return self._model

    # ---------------------------------------------------------------- контекст

    def _context(self, question: str = "") -> str:
        from . import memory
        from . import windows as win

        parts = [f"Сейчас: {clock.now_text()}."]
        owner = str(self._cfg.get("owner", "")).strip()
        if owner:
            parts.append(f"Человека зовут {owner} — обращайся по имени, но не в каждой фразе.")
        remembered = memory.context(question)
        if remembered:
            parts.append(remembered + ".")
        try:
            active = win.active_window()
            if active is not None and active.title:
                parts.append(f"Активное окно: «{active.title}» ({active.process}).")
        except Exception:  # noqa: BLE001 — контекст не обязателен
            pass
        return " ".join(parts)

    def _chat_system(self, question: str, extra: str = "") -> str:
        """Системная часть разговорного пути: характер плюс всё, что она о человеке знает.

        Раньше сюда не попадало ничего: имя, привычки и записанные факты видел
        только путь с инструментами. Из-за этого в обычном разговоре — там, где
        память нужнее всего — она общалась как с незнакомцем.
        """
        from . import language

        parts = [CHAT_PROMPT.replace("{SPEECH_RULE}", language.speech_rule()),
                 f"Контекст: {self._context(question)}"]
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    def reset(self) -> None:
        with self._lock:
            self._history = []

    def _remember(self, user_text: str, answer: str) -> None:
        limit = max(2, int(self._cfg.get("history_turns", 8))) * 2
        with self._lock:
            self._history = (
                self._history + [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
            )[-limit:]

    # ---------------------------------------------------------------- цикл

    def quick(self, text: str, context: str = "") -> str:
        """Быстрый разговорный ответ маленькой моделью, без инструментов.

        В звонке большая модель с полусотней инструментов думает секунды — для «как
        дела» это неоправданно. Простые реплики уходят в лёгкую модель и возвращаются
        почти мгновенно.
        """
        # Лёгкая модель отвечает быстрее, но её может не быть установлено. Тогда
        # берём основную — без инструментов и с коротким ответом. Это всё равно
        # заметно быстрее полного цикла и, главное, ничего не запускает: раньше
        # при отсутствии лёгкой модели разговор проваливался в агента с
        # инструментами, и «привет» мог обернуться открытым приложением.
        model = self._fast_model() or self._model
        if model is None:
            return ""
        history = [{"role": "system", "content": self._chat_system(text, context)},
                   *self._history[-4:], {"role": "user", "content": text}]

        # Лёгкая модель может числиться установленной, но не отвечать: Ollama
        # тогда возвращает 404 мгновенно. Разговор от этого не должен молчать —
        # переспрашиваем основную модель, и заодно больше не считаем лёгкую живой.
        message: Mapping[str, Any] = {}
        for candidate in dict.fromkeys((model, self._model)):
            if candidate is None:
                continue
            try:
                message = self._chat(history, tools_spec=None, num_predict=220,
                                     model=candidate, think=False)
                break
            except requests.RequestException:
                # Один сбой лёгкую модель не отменяет. Первый вызов холодной
                # модели легко упирается в таймаут, а пометка «не работает»
                # держалась до конца сеанса — и весь разговор потом шёл через
                # восьмимиллиардную модель, в десять раз медленнее.
                message = {}
        if not message:
            return ""
        answer = str(message.get("content") or "").strip()
        if answer:
            self._remember(text, answer)
        return answer

    def quick_stream(self, text: str, context: str = "") -> Iterator[str]:
        """То же, что `quick`, но текст отдаётся по мере генерации.

        Разница слышна сразу: синтез начинает говорить с первого готового
        предложения, а не после того, как модель допишет ответ целиком.
        """
        model = self._fast_model() or self._model
        if model is None:
            return
        history = [{"role": "system", "content": self._chat_system(text, context)},
                   *self._history[-6:], {"role": "user", "content": text}]
        collected: list[str] = []
        try:
            for piece in self._chat_stream(history, None, num_predict=220,
                                           model=model, think=False):
                collected.append(piece)
                yield piece
        except requests.RequestException:
            if not collected:
                return
        answer = "".join(collected).strip()
        if answer:
            self._remember(text, answer)

    def answer_from_web(self, question: str, query: str, context: str = "") -> Iterator[str]:
        """Отвечает на вопрос о мире по свежему поиску.

        Выбор инструмента здесь не доверяется модели: вопрос о фактах всегда идёт
        в поиск, а модель только пересказывает найденное. Это и быстрее цикла с
        инструментами, и не даёт ей выдумать цену или дату по памяти. Ничего не
        найдено — ничего не отдаёт, и вызывающий идёт обычным путём.
        """
        from . import web

        try:
            results = web.search_web(query, count=5)
        except Exception:  # noqa: BLE001 — нет сети или поисковик молчит
            return
        digest = "\n".join(
            f"{index}. {item.title} — {item.snippet}" for index, item in enumerate(results[:5], start=1)
        )
        if not digest.strip():
            return
        from . import language

        system = f"{WEB_PROMPT.replace('{SPEECH_RULE}', language.speech_rule())}\n\nКонтекст: {self._context(question)}"
        if context:
            system += f"\n{context}"
        messages = [
            {"role": "system", "content": system},
            *self._history[-4:],
            {"role": "user", "content": f"Вопрос: {question}\n\nВыдача поиска:\n{digest}"},
        ]
        collected: list[str] = []
        try:
            for piece in self._chat_stream(messages, None, num_predict=220, think=False,
                                           temperature=self._tool_temperature()):
                collected.append(piece)
                yield piece
        except requests.RequestException:
            if not collected:
                return
        answer = "".join(collected).strip()
        if answer:
            self._remember(question, answer)

    def _tool_temperature(self) -> float:
        """Температура для выбора инструментов и фактов.

        Разговору нужна живость, а выбору инструмента — точность. При общей
        температуре 0.57 модель то звала не тот инструмент, то переводила запрос
        на английский: «включи другую песню» превращалось в поиск «another song».
        """
        return float(self._cfg.get("tool_temperature", 0.15))

    def _fast_model(self) -> str | None:
        """Лёгкая модель для болтовни: берётся из настроек, если она установлена."""
        wanted = str(self._cfg.get("fast_model", "")).strip()
        if not wanted or not self.available():
            return None
        if self._fast_ok is None:
            try:
                response = self._session.get(f"{self.url}/api/tags", timeout=3)
                response.raise_for_status()
                names = [str(item.get("name", "")) for item in response.json().get("models", ())]
            except (requests.RequestException, ValueError):
                names = []
            self._fast_ok = any(name == wanted or name.startswith(wanted.split(":")[0]) for name in names)
        return wanted if self._fast_ok else None

    def run(self, text: str, on_step: StepCallback | None = None) -> str:
        """Выполняет запрос и возвращает готовый ответ целиком."""
        return "".join(self.run_stream(text, on_step=on_step))

    def run_stream(
        self,
        text: str,
        on_step: StepCallback | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        """Выполняет запрос: сколько угодно шагов инструментов, затем короткий ответ голосом.

        Итоговый ответ отдаётся кусками, поэтому синтез речи начинает говорить, не
        дожидаясь конца генерации. Промежуточные размышления и вызовы инструментов
        наружу не уходят — они видны только в журнале через `on_step`.
        """
        if not self.available():
            yield (
                "Модель не запущена. Открой терминал и выполни: ollama serve. "
                "Системные команды я выполняю и без неё."
            )
            return

        from . import language

        system_prompt = SYSTEM_PROMPT.replace("{SPEECH_RULE}", language.speech_rule())
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": f"{system_prompt}\n\nКонтекст: {self._context(text)}"},
            *self._history,
            {"role": "user", "content": text},
        ]
        # короткое «да» в ответ на вопрос о необратимом действии выполняет его
        # сразу, не тревожа модель: иначе она успевает передумать или уточнить
        answer = tools.resolve_pending(text)
        if answer is not None:
            if on_step is not None:
                on_step("tool_result", answer.text)
            yield answer.text
            return

        # инструменты, которые нельзя откатить, сверяются с этой фразой
        tools.set_request(text)
        specs = tools.select(text) if bool(self._cfg.get("route_tools", True)) else tools.specs()
        max_steps = int(self._cfg.get("max_steps", 8))
        used_tools = False
        # что уже сделано за эту просьбу, что падало и сколько было повторов:
        # на этом держится защита от бесконечного повторения действий
        performed: dict[str, str] = {}
        failures: dict[str, int] = {}
        repeats = 0
        needs_tool = _needs_tool(text)
        nudged = 0
        halt = should_stop or (lambda: False)

        for step in range(max_steps):
            # Отмену проверяем на границе шага. Оборвать уже начатое действие
            # нельзя — но следующее начинать незачем, если человек сказал «стоп».
            if halt():
                if on_step is not None:
                    on_step("error", "остановлено человеком")
                return
            # Пока инструменты ещё не вызывались, ответ придёт целиком: на первом
            # шаге модель обычно выбирает инструмент, и озвучивать её черновой
            # текст нельзя. После первого инструмента она уже подводит итог —
            # его отдаём голосу сразу, по мере генерации.
            voiced: list[str] = []
            try:
                if used_tools:
                    message = yield from self._chat_live(messages, specs, voiced,
                                                         temperature=self._tool_temperature())
                else:
                    message = self._chat(messages, specs, temperature=self._tool_temperature())
            except requests.RequestException as err:
                self._online = False
                if not voiced:
                    yield f"Модель не ответила: {err.__class__.__name__}. Проверь, запущена ли Ollama."
                return

            calls = _tool_calls(message)
            content = str(message.get("content") or "").strip()

            if voiced and not calls:
                # текст уже прозвучал по ходу генерации — второй раз не повторяем
                self._remember(text, content or "".join(voiced))
                return

            if not calls:
                unverified = _claims_action(content) or needs_tool
                if not used_tools and unverified and nudged < 2 and step + 1 < max_steps:
                    # модель отчиталась о действии или о состоянии системы, ничего не проверив
                    nudged += 1
                    if on_step is not None:
                        on_step("error", "ответ без инструмента — требую выполнить по-настоящему")
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": "Ты не вызвал ни одного инструмента, значит действие не выполнено, "
                            "а данные не проверены. Сейчас же вызови подходящий инструмент и ответь "
                            "только по его результату.",
                        }
                    )
                    continue
                if not used_tools and _needs_action(text):
                    # действие требовалось, но ни один инструмент не сработал — не врём
                    answer = (
                        "Не получилось: не поняла, каким действием это сделать. "
                        "Скажи по-другому — например, «открой телеграм»."
                    )
                    self._remember(text, answer)
                    yield answer
                    return
                if not content:
                    # Пустой ответ модели — не «готово». Раньше это заглушалось
                    # словом-затычкой, и на «привет, как дела» человек слышал
                    # «Готово.». Разговорную реплику доводит до ума лёгкий путь.
                    answer = self.quick(text) or _summary(performed) or "Не понял, повтори?"
                else:
                    answer = content
                self._remember(text, answer)
                yield answer
                return

            messages.append({"role": "assistant", "content": content, "tool_calls": message.get("tool_calls", [])})
            if content and on_step is not None:
                on_step("thought", content)

            for call in calls:
                if halt():
                    if on_step is not None:
                        on_step("error", "остановлено человеком")
                    return
                used_tools = True
                name, arguments = call
                signature = _signature(name, arguments)

                # Уже выполненный вызов не повторяем. Модель, не увидев нужного
                # результата, охотно зовёт тот же инструмент по кругу: раньше это
                # и давало бесконечное повторение действия.
                done = performed.get(signature)
                if done is not None:
                    if on_step is not None:
                        on_step("error", f"повтор {name}: шаг уже выполнен")
                    messages.append({
                        "role": "tool", "name": name, "tool_name": name,
                        "content": f"ЭТОТ ШАГ УЖЕ ВЫПОЛНЕН РАНЕЕ, результат: {done[:400]}. "
                                   "Не вызывай его снова. Переходи к следующему шагу "
                                   "или заверши задачу ответом.",
                    })
                    repeats += 1
                    if repeats >= 2:
                        answer = _summary(performed) or "Задача выполнена."
                        self._remember(text, answer)
                        yield answer
                        return
                    continue

                if on_step is not None:
                    on_step("tool", f"{name}({_short(arguments)})")
                result = tools.call(name, arguments)
                if on_step is not None:
                    on_step("tool_result" if result.ok else "error", result.text)

                if result.ok:
                    performed[signature] = result.text
                    failures.pop(name, None)
                else:
                    # один и тот же инструмент, падающий второй раз, не починится
                    # с третьей попытки — задача невыполнима, и врать об этом нельзя
                    failures[name] = failures.get(name, 0) + 1
                    if failures[name] >= 2:
                        answer = (f"Не смог: «{name}» не отработал дважды подряд. "
                                  f"Последняя ошибка: {result.text[:160]}")
                        self._remember(text, answer)
                        yield answer
                        return
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "tool_name": name,
                        "content": result.for_model()[:2000],
                    }
                )

        # шаги кончились — просим короткий итог без новых инструментов
        tail = messages + [
            {"role": "user", "content": "Подведи короткий итог: что реально выполнено."}
        ]
        voiced = []
        try:
            final = yield from self._chat_live(tail, None, voiced, temperature=self._tool_temperature())
            answer = str(final.get("content") or "").strip()
        except requests.RequestException:
            answer = ""
        if voiced:
            self._remember(text, answer or "".join(voiced))
            return
        answer = answer or _summary(performed) or "Выполнил, что смог."
        self._remember(text, answer)
        yield answer

    def ask(self, prompt: str, num_predict: int = 160) -> str:
        """Одиночный вопрос к модели без инструментов и без истории — для служебных задач."""
        if not self.available():
            return ""
        message = self._chat(
            [{"role": "user", "content": prompt}], tools_spec=None, num_predict=num_predict
        )
        return str(message.get("content") or "").strip()

    # ---------------------------------------------------------------- транспорт

    def _chat(
        self,
        messages: list[dict[str, Any]],
        tools_spec: list[dict[str, Any]] | None,
        num_predict: int | None = None,
        model: str | None = None,
        think: bool | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        # Размышление выключаем всегда, когда оно не заказано настройкой. Раньше
        # это делалось только если Ollama объявила возможность «thinking», а она
        # объявляет её не всегда: qwen3 тратил весь лимит токенов на размышление,
        # возвращал пустой content, и человек слышал «Готово.» вместо ответа.
        payload = self._payload(messages, tools_spec, num_predict, model, think, temperature)
        message = self._post(payload)

        # Рассуждающая модель (qwen3 и подобные) может истратить весь лимит
        # токенов на размышление и вернуть пустой ответ: текст уходит в поле
        # thinking, а content остаётся пустым. Список возможностей Ollama не
        # всегда объявляет «thinking», поэтому чиним по факту — один повтор с
        # явно выключенным размышлением. Заодно ответ приходит заметно быстрее.
        empty = not str(message.get("content") or "").strip()
        if empty and message.get("thinking") and not message.get("tool_calls"):
            if not self._cfg.get("think", False):
                payload["think"] = False
                self._capabilities = tuple({*self._capabilities, "thinking"})
                message = self._post(payload)
        return message

    def _chat_live(
        self,
        messages: list[dict[str, Any]],
        tools_spec: list[dict[str, Any]] | None,
        voiced: list[str],
        temperature: float | None = None,
    ) -> Iterator[str]:
        """Запрос с потоковой отдачей текста наружу; возвращает собранное сообщение.

        Куски уходят наружу (в синтез речи) только пока модель не позвала ни одного
        инструмента. Стоит появиться вызову — отдача прекращается: озвучивать
        служебный текст, за которым последует действие, нельзя. Всё сказанное
        складывается в `voiced`, чтобы вызывающий знал, что уже прозвучало.
        """
        collected: list[str] = []
        calls: list[Any] = []
        held = ""     # придержанное начало: вдруг за ним последует вызов инструмента
        muted = False  # текст оказался служебным — до конца ответа молчим

        for piece, chunk_calls in self._chat_stream_raw(messages, tools_spec, temperature=temperature):
            if chunk_calls:
                calls.extend(chunk_calls)
                held = ""  # начало оказалось присказкой перед действием — не озвучиваем
            if not piece:
                continue
            collected.append(piece)
            if calls or muted:
                continue

            held += piece
            # Мелкие модели иногда пишут вызов инструмента прямо текстом. Разобрать
            # его сумеет `_tool_calls`, но озвучивать нельзя: человек услышал бы
            # вслух фигурные скобки и имя функции.
            if _LOOKS_LIKE_CALL.search("".join(collected)):
                held, muted = "", True
                continue
            # Первые слова придерживаем. Модель иногда начинает с «Сейчас открою…»
            # и только потом зовёт инструмент: озвученная присказка звучала бы как
            # отчёт о том, чего ещё не случилось.
            if len(held) < _VOICE_HOLD and not held.rstrip().endswith((".", "!", "?")):
                continue
            voiced.append(held)
            yield held
            held = ""

        if held and not calls and not muted:
            voiced.append(held)
            yield held
        message: dict[str, Any] = {"content": "".join(collected)}
        if calls:
            message["tool_calls"] = calls
        return message

    def _chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools_spec: list[dict[str, Any]] | None,
        num_predict: int | None = None,
        model: str | None = None,
        think: bool | None = None,
        temperature: float | None = None,
    ) -> Iterator[str]:
        """Тот же запрос, но ответ приходит кусками текста по мере генерации."""
        for piece, _ in self._chat_stream_raw(
            messages, tools_spec, num_predict, model, think, temperature
        ):
            if piece:
                yield piece

    def _chat_stream_raw(
        self,
        messages: list[dict[str, Any]],
        tools_spec: list[dict[str, Any]] | None,
        num_predict: int | None = None,
        model: str | None = None,
        think: bool | None = None,
        temperature: float | None = None,
    ) -> Iterator[tuple[str, list[Any]]]:
        """Поток Ollama как пары (кусок текста, вызовы инструментов из этого кадра)."""
        payload = self._payload(messages, tools_spec, num_predict, model, think, temperature)
        payload["stream"] = True
        response = self._session.post(
            f"{self.url}/api/chat", json=payload, stream=True,
            timeout=float(self._cfg.get("timeout_s", 120)),
        )
        if response.status_code == 400 and "think" in payload:
            response.close()
            payload.pop("think", None)
            response = self._session.post(
                f"{self.url}/api/chat", json=payload, stream=True,
                timeout=float(self._cfg.get("timeout_s", 120)),
            )
        response.raise_for_status()
        try:
            for line in response.iter_lines(decode_unicode=False):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                message = data.get("message")
                if isinstance(message, Mapping):
                    raw_calls = message.get("tool_calls") or []
                    piece = str(message.get("content") or "")
                    if piece or raw_calls:
                        yield piece, list(raw_calls)
                if data.get("done"):
                    break
        finally:
            response.close()

    def _payload(
        self,
        messages: list[dict[str, Any]],
        tools_spec: list[dict[str, Any]] | None,
        num_predict: int | None = None,
        model: str | None = None,
        think: bool | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self._model or str(self._cfg.get("model")),
            "stream": False,
            "keep_alive": _KEEP_ALIVE,
            "messages": messages,
            "options": {
                "temperature": float(temperature if temperature is not None
                                     else self._cfg.get("temperature", 0.3)),
                "num_predict": int(num_predict or self._cfg.get("num_predict", 400)),
                "num_ctx": int(self._cfg.get("num_ctx", 8192)),
            },
        }
        if tools_spec:
            payload["tools"] = tools_spec
        wanted = think if think is not None else bool(self._cfg.get("think", False))
        if not wanted or "thinking" in self._capabilities:
            payload["think"] = wanted
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(
            f"{self.url}/api/chat", json=payload, timeout=float(self._cfg.get("timeout_s", 120))
        )
        # модель без поддержки размышления отвечает на это поле отказом —
        # повторяем без него, вместо того чтобы остаться совсем без ответа
        if response.status_code == 400 and "think" in payload:
            payload.pop("think", None)
            response = self._session.post(
                f"{self.url}/api/chat", json=payload, timeout=float(self._cfg.get("timeout_s", 120))
            )
        response.raise_for_status()
        data = response.json()
        message = data.get("message")
        return message if isinstance(message, Mapping) else {}


# ---------------------------------------------------------------- разбор ответа модели


# Признаки того, что модель пишет вызов инструмента текстом, а не отвечает.
# Проверяется до озвучивания: такой «ответ» нельзя читать вслух.
_LOOKS_LIKE_CALL = re.compile(
    r"<tool_call>|\{\s*\"(?:name|tool|arguments|parameters)\"|"
    # `read_screen(...)` или `-read_screen()` — вызов, записанный текстом. Модель
    # иногда пишет его вместо того, чтобы вызвать: озвучивать такое нельзя.
    r"(?:^|[\s\-*•])[a-z_]{3,32}\s*[\{(]",
    re.MULTILINE,
)

_TOOL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*(?:</tool_call>)?", re.DOTALL)
_TOOL_JSON = re.compile(r'\{\s*"(?:name|tool)"\s*:\s*"([a-z_]+)"\s*,\s*"(?:arguments|parameters)"\s*:\s*(\{.*?\})\s*\}', re.DOTALL)
# Вызов, записанный текстом: «read_screen», «-read_screen()», «list_controls {}».
# Скобки и маркер списка модель добавляет охотно, и без них разбор промахивался.
_TOOL_PLAIN = re.compile(r"^[\s\-*•]*([a-z_]{3,32})\s*(?:\(\s*\)|\((.*?)\)|(\{.*\}))?\s*$", re.MULTILINE)


def _parse_text_calls(content: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Мелкие модели иногда пишут вызов текстом. Разбираем и такие формы, а не игнорируем."""
    if not content:
        return ()
    known = set(tools.names())
    found: list[tuple[str, dict[str, Any]]] = []

    for match in _TOOL_TAG.finditer(content):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        name = str(payload.get("name") or payload.get("tool") or "")
        arguments = payload.get("arguments") or payload.get("parameters") or {}
        if name in known and isinstance(arguments, Mapping):
            found.append((name, dict(arguments)))

    if not found:
        for name, raw in _TOOL_JSON.findall(content):
            if name not in known:
                continue
            try:
                found.append((name, dict(json.loads(raw))))
            except (json.JSONDecodeError, TypeError, ValueError):
                found.append((name, {}))

    if not found:
        for name, inner, braced in _TOOL_PLAIN.findall(content):
            if name not in known:
                continue
            raw = braced or inner or ""
            try:
                arguments = json.loads(raw) if raw.strip().startswith("{") else {}
            except json.JSONDecodeError:
                arguments = {}
            found.append((name, dict(arguments) if isinstance(arguments, Mapping) else {}))

    return tuple(found[:3])


def _tool_calls(message: Mapping[str, Any]) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Вызовы инструментов из ответа. Аргументы иногда приходят строкой JSON."""
    raw = message.get("tool_calls") or ()
    calls: list[tuple[str, dict[str, Any]]] = []
    for item in raw:
        function = item.get("function") if isinstance(item, Mapping) else None
        if not isinstance(function, Mapping):
            continue
        name = str(function.get("name", "")).strip()
        if not name:
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        calls.append((name, dict(arguments) if isinstance(arguments, Mapping) else {}))
    if calls:
        return tuple(calls)
    return _parse_text_calls(str(message.get("content") or ""))


_ACTION_CLAIM = re.compile(
    r"\b(?:откр\w+|запуск\w+|запустил\w*|включ\w+|выключ\w+|сверн\w+|напечат\w+|отправ\w+|"
    r"создал\w*|удалил\w*|нашёл|нашел|сделал\w*|выполнил\w*|установ\w+|изменил\w*|задал\w*|"
    r"поставил\w*|скопирова\w+|перемест\w+|готово|opening|launching|done)\b",
    re.IGNORECASE,
)

# фразы, для которых ответ без инструмента заведомо выдуман: команды и состояние системы
_TOOL_REQUIRED = re.compile(
    r"\b(?:открой|открыть|запусти|включи|выключи|закрой|сверни|разверни|поставь|сделай|создай|"
    r"удали|скопируй|перемести|переименуй|напиши|напечатай|набери|отправь|нажми|кликни|найди|"
    r"поищи|погугли|прочитай|покажи|проверь|посмотри|скачай|перейди|громкост\w+|яркост\w+|"
    r"погод\w+|новост\w+|скриншот|снимок|курс|котировк\w+|"
    r"что\s+на\s+экране|какие\s+окна|запущено|свободн\w+|батаре\w+|памят\w+|процессор\w*|диск\w*)\b",
    re.IGNORECASE,
)


def _claims_action(text: str) -> bool:
    return bool(text) and bool(_ACTION_CLAIM.search(text))


# прямые приказы: если ни один инструмент не сработал, отчитываться об успехе нельзя
_ACTION_ORDER = re.compile(
    r"\b(?:открой|открыть|запусти|включи|выключи|закрой|сверни|разверни|поставь|создай|удали|"
    r"скопируй|перемести|переименуй|напиши|напечатай|набери|отправь|нажми|кликни|сделай\s+скриншот|"
    r"заблокируй|перезагрузи|скачай|перейди|прокрути|найди\s+файл)\b",
    re.IGNORECASE,
)


def _needs_tool(text: str) -> bool:
    """Запрос требует проверки в системе или в сети — отвечать по памяти нельзя."""
    return bool(_TOOL_REQUIRED.search(text or "")) or _needs_action(text)


def _needs_action(text: str) -> bool:
    """Фраза — прямой приказ что-то сделать с компьютером."""
    return bool(_ACTION_ORDER.search(text or ""))


def _signature(name: str, arguments: Mapping[str, Any]) -> str:
    """Отпечаток вызова: тот же инструмент с теми же доводами — тот же шаг.

    Порядок ключей от модели приходит разный, поэтому доводы сортируются:
    иначе один и тот же шаг выглядел бы каждый раз новым.
    """
    try:
        body = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        body = str(sorted((arguments or {}).items()))
    return f"{name}:{body}"


def _summary(performed: Mapping[str, str]) -> str:
    """Короткий отчёт о том, что действительно выполнено."""
    if not performed:
        return ""
    last = list(performed.values())[-1].strip()
    done = len(performed)
    tail = f" Последний шаг: {last[:160]}" if last else ""
    return f"Готово, шагов выполнено: {done}.{tail}"


def _short(arguments: Mapping[str, Any], limit: int = 90) -> str:
    text = ", ".join(f"{key}={value}" for key, value in arguments.items())
    return text if len(text) <= limit else text[: limit - 1] + "…"
