/**
 * Разговор с предприятием: сцена, числа, голос.
 *
 * Порядок событий здесь важнее любой отдельной части. Числа и камера трогаются
 * сразу, как только сервер посчитал, — это доли секунды. Речь идёт следом,
 * предложение за предложением, и синтез каждого начинается, пока предыдущее ещё
 * звучит. Собранные вместе, эти три задержки дали бы паузу секунд в пять, и
 * разговор превратился бы в отправку запроса; разложенные по очереди, они
 * складываются в ощущение, что предприятие отвечает сразу.
 */

import { Factory } from '/page/twin/scene.js';

const $ = (id) => document.getElementById(id);
const stage = $('view'), labels = $('labels'), speech = $('speech');
const answer = $('answer'), aTitle = $('a-title'), aFacts = $('a-facts');
const field = $('q'), mic = $('mic'), knobs = $('knobs'), boot = $('boot');

let factory = null;
let socket = null;
let base = null;         // состояние без сценария — к нему возвращает сброс
let plan = {};           // текущий сценарий: участок → дельта людей

/* ------------------------------------------------------------------ */
/* Числа на панели                                                     */
/* ------------------------------------------------------------------ */

const money = (value) => {
  if (Math.abs(value) >= 1e6) return (value / 1e6).toFixed(1).replace('.', ',') + ' млн ₽';
  if (Math.abs(value) >= 1e3) return Math.round(value / 1e3) + ' тыс ₽';
  return Math.round(value) + ' ₽';
};
const plural = (n, one, few, many) => {
  if (n !== Math.trunc(n)) return few;
  const a = Math.abs(n) % 10, b = Math.abs(n) % 100;
  if (a === 1 && b !== 11) return one;
  if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
  return many;
};
const days = (v) => v.toFixed(1).replace('.', ',') + ' ' + plural(Math.round(v * 10) / 10, 'день', 'дня', 'дней');

function vitals(state) {
  const set = (id, text, accent) => {
    const box = $(id);
    box.textContent = text;
    box.className = accent || '';
  };
  // Норма остаётся без класса и потому бесцветной. Красить «хорошо» зелёным —
  // значит тратить внимание зрителя там, где смотреть не на что.
  set('v-lead', days(state.lead_days), state.lead_days > 7 ? 'crit' : '');
  set('v-late', Math.round(state.late_share * 100) + '%',
      state.late_share > 0.25 ? 'crit' : state.late_share > 0.05 ? 'warn' : '');
  set('v-wip', state.wip + ' ' + plural(state.wip, 'заказ', 'заказа', 'заказов'),
      state.wip > 150 ? 'crit' : state.wip > 60 ? 'warn' : '');
  set('v-flow', state.completed_day.toFixed(1).replace('.', ',') + ' из ' + state.orders_day,
      state.completed_day < state.orders_day - 0.5 ? 'warn' : '');
  set('v-rev', money(state.revenue_month));
  const neck = state.stations.find((item) => item.id === state.bottleneck);
  set('v-neck', neck ? `${neck.name} · ${Math.round(neck.load * 100)}%` : '—',
      neck && neck.load >= 0.98 ? 'crit' : 'warn');
  $('plant').textContent = state.name.toLowerCase();
}

function facts(reading) {
  aTitle.textContent = reading.title;
  aFacts.innerHTML = '';
  reading.facts.forEach((item, i) => {
    const row = document.createElement('div');
    row.className = 'fact';
    // Задержка на карточку небольшая, но не нулевая: факты, появившиеся разом,
    // читаются как таблица, а появляющиеся друг за другом — как рассуждение.
    row.style.animationDelay = (i * 65) + 'ms';
    row.innerHTML = `<span></span><b class="${item.accent === 'plain' ? '' : item.accent}"></b>`;
    row.querySelector('span').textContent = item.label;
    row.querySelector('b').textContent = item.value;
    aFacts.appendChild(row);
  });
  answer.classList.add('on');
}

/* ------------------------------------------------------------------ */
/* Голос                                                               */
/* ------------------------------------------------------------------ */

let audio = null, meter = null, queue = Promise.resolve(), speaking = 0;

/** Разбор звука на громкость — им дышит свет вокруг проводника. */
function ear() {
  if (audio) return audio;
  audio = new (window.AudioContext || window.webkitAudioContext)();
  meter = audio.createAnalyser();
  meter.fftSize = 256;
  meter.connect(audio.destination);
  const data = new Uint8Array(meter.frequencyBinCount);
  const watch = () => {
    meter.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
    factory?.setLevel(Math.min(1, Math.sqrt(sum / data.length) * 3.4));
    requestAnimationFrame(watch);
  };
  watch();
  return audio;
}

/**
 * Ставит фразу в очередь озвучки.
 *
 * Загрузка следующей фразы начинается сразу, а проигрывание ждёт своей очереди.
 * Иначе между предложениями возникает провал на время синтеза — заметный на слух
 * и разрушающий впечатление живой речи сильнее, чем любая задержка в начале.
 */
function say(text) {
  const context = ear();
  if (context.state === 'suspended') context.resume();
  const loading = fetch('/api/twin/voice?text=' + encodeURIComponent(text))
    .then((response) => (response.ok ? response.arrayBuffer() : Promise.reject(new Error('нет голоса'))))
    .then((bytes) => context.decodeAudioData(bytes))
    .catch(() => null);

  queue = queue.then(async () => {
    const sound = await loading;
    speech.textContent = text;
    speech.classList.add('on');
    if (!sound) { await new Promise((done) => setTimeout(done, 40 * text.length)); return; }
    speaking++;
    factory?.setState('speaking');
    await new Promise((done) => {
      const source = context.createBufferSource();
      source.buffer = sound;
      source.connect(meter);
      source.onended = () => { speaking--; if (!speaking) factory?.setState('idle'); done(); };
      source.start();
    });
  });
  return queue;
}

/* ------------------------------------------------------------------ */
/* Разговор                                                            */
/* ------------------------------------------------------------------ */

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${protocol}://${location.host}/twin/ws`);
  socket.onmessage = (event) => {
    const packet = JSON.parse(event.data);
    if (packet.type === 'start') {
      factory?.setState('thinking');
      speech.classList.remove('on');
      answer.classList.remove('on');
    } else if (packet.type === 'reading') {
      facts(packet);
      factory?.focus(packet.focus, packet.camera);
    } else if (packet.type === 'state') {
      factory?.update(packet.state);
      vitals(packet.state);
    } else if (packet.type === 'say') {
      say(packet.text);
    } else if (packet.type === 'error') {
      speech.textContent = packet.text;
      speech.classList.add('on');
      factory?.setState('idle');
    } else if (packet.type === 'done') {
      queue.then(() => setTimeout(() => speech.classList.remove('on'), 2600));
    }
  };
  socket.onclose = () => setTimeout(connect, 1500);
}

function ask(question) {
  const text = (question || field.value).trim();
  if (!text || socket?.readyState !== WebSocket.OPEN) return;
  ear();
  field.value = '';
  socket.send(JSON.stringify({ question: text }));
}

$('ask').addEventListener('submit', (event) => { event.preventDefault(); ask(); });
$('hints').addEventListener('click', (event) => {
  if (event.target.tagName === 'BUTTON') ask(event.target.textContent);
});

/* ------------------------------------------------------------------ */
/* Голосовой ввод                                                      */
/* ------------------------------------------------------------------ */

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (Recognition) {
  const listener = new Recognition();
  listener.lang = 'ru-RU';
  listener.interimResults = true;
  listener.continuous = false;
  let heard = '';
  mic.addEventListener('click', () => {
    ear();
    if (mic.classList.contains('live')) { listener.stop(); return; }
    heard = '';
    try { listener.start(); } catch { /* уже слушает */ }
  });
  listener.onstart = () => mic.classList.add('live');
  listener.onend = () => {
    mic.classList.remove('live');
    if (heard.trim()) ask(heard);
  };
  listener.onerror = () => mic.classList.remove('live');
  listener.onresult = (event) => {
    let text = '';
    for (let i = 0; i < event.results.length; i++) text += event.results[i][0].transcript;
    heard = text;
    field.value = text;   // видно, что услышано, — иначе непонятно, почему ответ не тот
  };
} else {
  mic.title = 'Браузер не умеет распознавать речь — спросите текстом';
  mic.style.opacity = '.4';
}

/* ------------------------------------------------------------------ */
/* Сценарий                                                            */
/* ------------------------------------------------------------------ */

let pending = null;

function push() {
  clearTimeout(pending);
  // Небольшая пауза перед расчётом: нажатия подряд — это один замысел, а не
  // четыре разных сценария, и считать стоит только последний.
  pending = setTimeout(async () => {
    const answerPacket = await fetch('/api/twin/scenario', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ staff: plan }),
    }).then((response) => response.json());
    factory?.update(answerPacket.state);
    vitals(answerPacket.state);
    if (answerPacket.reading) {
      facts(answerPacket.reading);
      factory?.focus(answerPacket.reading.focus, 'dive');
    } else {
      answer.classList.remove('on');
    }
  }, 220);
}

function buildKnobs(state) {
  knobs.innerHTML = '';
  for (const station of state.stations) {
    const row = document.createElement('div');
    row.className = 'knob';
    row.innerHTML = `<label title="${station.name}">${station.name}</label>
      <button class="step" data-d="-1" type="button">−</button>
      <output>0</output>
      <button class="step" data-d="1" type="button">+</button>`;
    const out = row.querySelector('output');
    row.querySelectorAll('.step').forEach((button) => {
      button.addEventListener('click', () => {
        const next = (plan[station.id] || 0) + Number(button.dataset.d);
        // Нижняя граница — минус все, кроме одного: участок без людей не участок,
        // и симуляция такого просто не имеет смысла считать.
        plan[station.id] = Math.max(1 - station.staff, Math.min(10, next));
        const delta = plan[station.id];
        out.textContent = (delta > 0 ? '+' : '') + delta;
        out.className = delta > 0 ? 'plus' : delta < 0 ? 'minus' : '';
        push();
      });
    });
    knobs.appendChild(row);
  }
}

$('reset').addEventListener('click', () => {
  plan = {};
  knobs.querySelectorAll('output').forEach((out) => { out.textContent = '0'; out.className = ''; });
  factory?.update(base);
  vitals(base);
  answer.classList.remove('on');
  factory?.focus(base.bottleneck, 'wide');
});

/* ------------------------------------------------------------------ */
/* Запуск                                                              */
/* ------------------------------------------------------------------ */

(async function start() {
  base = await fetch('/api/twin/plant').then((response) => response.json());
  factory = new Factory(stage, labels);
  factory.onPick(async (id) => {
    const reading = await fetch('/api/twin/station/' + id).then((response) => response.json());
    facts(reading);
    factory.focus(id, 'orbit');
  });
  await factory.build(base, '/page/assets/samurai.glb');
  vitals(base);
  buildKnobs(base);
  connect();
  boot.classList.add('gone');

  // Открывающий проход: камера стоит вплотную к проводнику, держит его пару
  // секунд и отъезжает, открывая линию. Порядок именно такой — сначала
  // фигура, потом масштаб. Начав с общего плана, зритель видит схему и уже не
  // возвращается к персонажу; начав с фигуры, он смотрит на цех её глазами.
  factory.focus(null, 'hero');
  setTimeout(() => factory.focus(base.bottleneck, 'wide'), 2900);
})();
