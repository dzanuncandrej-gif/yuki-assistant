/**
 * Пульт «Диалог»: ядро из частиц слева, переписка справа.
 *
 * Страница ничего не решает сама — она только показывает события ядра Юки
 * (состояние, уровень звука, реплики, шаги агента) и отправляет наверх то,
 * что человек написал или нажал.
 */
import { connect, escapeHtml, parse } from './link.js';
import { render, wireCopy } from './markdown.js';
import { createOrb } from './orb.js';

const SIGNALS = ['event', 'stats', 'history'];
const SLOTS = ['ready', 'sendText', 'setMuted', 'interrupt', 'reset', 'startCall', 'copyText'];

const STATE_TEXT = { idle: 'ожидание', listening: 'слушаю', thinking: 'думаю', speaking: 'говорю', acting: 'действую', muted: 'микрофон выкл' };
const LOGO = '<svg viewBox="0 0 100 100"><path d="M31 28 L50 52 L69 28 M50 52 L50 78"/></svg>';

const $ = (id) => document.getElementById(id);
const els = {
  hub: document.querySelector('.hub'), list: $('list'), scroll: $('scroll'), empty: $('empty'),
  input: $('input'), composer: $('composer'), subtitle: $('subtitle'), hint: $('hint'),
  statePill: $('state-pill'), stateText: $('state-text'), modelPill: $('model-pill'), modelText: $('model-text'),
  mic: $('mic'), counter: $('counter'), cpu: $('cpu'), ram: $('ram'), voice: $('voice'),
};

let orb = null;
try {
  orb = createOrb(document.querySelector('.gl'), { count: 30000, zoom: 12, size: 1.45 });
  orb.place(0, 0.12, 0.92);
  orb.mode('greeting');
  setTimeout(() => orb.mode('idle'), 1800);
} catch (err) {
  console.warn('WebGL недоступен', err);
}

let link = null;
let muted = false;
let state = 'idle';
let turn = null;        // текущий ход: блок шагов и «печатающийся» ответ
let count = 0;
let subtitleTimer = 0;

/* ------------------------------------------------------------------ сообщения */

function scrollDown() {
  requestAnimationFrame(() => { els.scroll.scrollTop = els.scroll.scrollHeight; });
}

function bump() {
  count += 1;
  els.empty.hidden = true;
  els.counter.textContent = `${count} ${plural(count, 'сообщение', 'сообщения', 'сообщений')}`;
}

function plural(n, one, few, many) {
  const m10 = n % 10; const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

function time(ts) {
  const d = ts ? new Date(ts * 1000) : new Date();
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

function looksLikeMarkdown(text) {
  return /\n\s*([-*•]|\d+[.)])\s|```|^#{1,4}\s|\*\*[^*]+\*\*/m.test(text);
}

function addMessage(kind, text, ts, { animate = true } = {}) {
  const li = document.createElement('li');
  li.className = `msg msg--${kind}`;
  if (!animate) li.style.animation = 'none';
  const who = { user: 'ты', assistant: 'юки', error: 'ошибка', report: 'юки · разбор' }[kind] || kind;
  const body = kind === 'report' || (kind === 'assistant' && looksLikeMarkdown(text))
    ? `<div class="md">${render(text)}</div>`
    : `<div class="msg__text">${escapeHtml(text)}</div>`;
  if (kind === 'report') {
    li.innerHTML = `<div class="msg__avatar">${LOGO}</div><div class="msg__body"><div class="report__head"><span>РАЗВЁРНУТЫЙ ОТВЕТ · ${time(ts)}</span><button type="button" data-copy-all>копировать всё</button></div>${body}</div>`;
    li.querySelector('[data-copy-all]').addEventListener('click', (e) => {
      link?.copyText(text);
      e.target.textContent = 'скопировано';
      setTimeout(() => { e.target.textContent = 'копировать всё'; }, 1600);
    });
  } else if (kind === 'user') {
    li.innerHTML = `<div class="msg__body"><div class="msg__meta">${who} · ${time(ts)}</div>${body}</div>`;
  } else {
    li.innerHTML = `<div class="msg__avatar">${LOGO}</div><div class="msg__body"><div class="msg__meta">${who} · ${time(ts)}</div>${body}</div>`;
  }
  els.list.append(li);
  bump();
  scrollDown();
  return li;
}

function stepsBlock() {
  if (turn?.steps) return turn.steps;
  const box = document.createElement('li');
  box.className = 'steps';
  box.innerHTML = '<div class="steps__head">Юки работает…</div><ol></ol>';
  box.querySelector('.steps__head').addEventListener('click', () => box.classList.toggle('is-open'));
  els.list.append(box);
  turn = turn || {};
  turn.steps = box;
  turn.calls = 0;
  return box;
}

function addStep(text) {
  if (/^мимо/.test(text)) return;       // фраза без обращения — это шум, а не шаг
  const box = stepsBlock();
  const li = document.createElement('li');
  let cls = 'note'; let mark = '·'; let body = text;
  if (text.startsWith('→')) { cls = 'call'; mark = '→'; body = text.slice(1).trim(); turn.calls += 1; setState('acting'); }
  else if (text.startsWith('✓')) { cls = 'done'; mark = '✓'; body = text.slice(1).trim(); orb?.pulse(0.35); }
  li.className = cls;
  li.innerHTML = `<b>${mark}</b><span>${escapeHtml(body)}</span>`;
  box.querySelector('ol').append(li);
  const calls = turn.calls;
  box.querySelector('.steps__head').textContent = calls
    ? `Юки работает · ${calls} ${plural(calls, 'действие', 'действия', 'действий')}`
    : 'Юки думает…';
  scrollDown();
}

function closeSteps(failed = false) {
  if (!turn?.steps) return;
  const box = turn.steps;
  box.classList.add('is-done');
  const calls = turn.calls || 0;
  box.querySelector('.steps__head').textContent = failed
    ? 'не получилось — подробности внутри'
    : calls ? `готово · ${calls} ${plural(calls, 'действие', 'действия', 'действий')}` : 'ход мыслей';
}

function typing(text) {
  if (!turn) turn = {};
  if (!turn.typing) {
    turn.typing = addMessage('assistant', '', null);
    turn.typing.classList.add('msg--typing');
    count -= 1;
  }
  turn.typing.querySelector('.msg__text').textContent = text;
  scrollDown();
}

function finishAssistant(text, ts) {
  closeSteps();
  if (turn?.typing) {
    const bubble = turn.typing;
    bubble.classList.remove('msg--typing');
    const holder = bubble.querySelector('.msg__text');
    if (looksLikeMarkdown(text)) holder.outerHTML = `<div class="md">${render(text)}</div>`;
    else holder.textContent = text;
    bump();
  } else if (text.trim()) {
    addMessage('assistant', text, ts);
  }
  turn = null;
}

function onMessage(kind, text, ts, animate = true) {
  if (kind === 'user') {
    closeSteps();
    turn = null;
    addMessage('user', text, ts, { animate });
    turn = {};
    return;
  }
  if (kind === 'assistant') { if (animate) finishAssistant(text, ts); else addMessage('assistant', text, ts, { animate }); return; }
  if (kind === 'report') { addMessage('report', text, ts, { animate }); return; }
  if (kind === 'error') {
    if (turn?.steps) { addStep(`✗ ${text}`); turn.steps.querySelector('ol').lastChild.className = 'fail'; }
    else addMessage('error', text, ts, { animate });
    if (animate && orb) { orb.mode('error'); orb.pulse(0.8); setTimeout(() => orb.mode(orbMode(state)), 1600); }
    return;
  }
  if (kind === 'system' && animate && turn) addStep(text);
}

/* ------------------------------------------------------------------ состояние */

function orbMode(name) {
  if (muted) return 'muted';
  return { acting: 'acting', thinking: 'thinking', speaking: 'speaking', listening: 'listening' }[name] || 'idle';
}

// Плавно всегда; в фоне окна — вдвое реже, его всё равно никто не смотрит.
const STATE_FPS = { thinking: 60, acting: 60, speaking: 60, listening: 60, idle: 60, muted: 60 };
let focused = document.hasFocus();

function applyFps() {
  if (!orb) return;
  const base = STATE_FPS[state] || 20;
  orb.setFps(focused ? base : 30);
}
window.addEventListener('focus', () => { focused = true; applyFps(); });
window.addEventListener('blur', () => { focused = false; applyFps(); });

function setState(name) {
  state = name;
  applyFps();
  const shown = muted && name !== 'speaking' ? 'muted' : name;
  els.statePill.dataset.state = shown;
  els.stateText.textContent = STATE_TEXT[shown] || name;
  els.hint.style.opacity = name === 'speaking' || name === 'thinking' ? 0 : 1;
  orb?.mode(orbMode(name));
}

function setSubtitle(text) {
  els.subtitle.textContent = text;
  clearTimeout(subtitleTimer);
  subtitleTimer = setTimeout(() => { els.subtitle.textContent = ''; }, 6000);
}

function onEvent(raw) {
  const ev = parse(raw);
  if (!ev) return;
  switch (ev.type) {
    case 'state':
      if (!(state === 'acting' && ev.state === 'thinking')) setState(ev.state);
      if (orb) orb.target.amp = 0;
      break;
    case 'level':
      if (orb) orb.target.amp = Math.min(0.6, (ev.level || 0) * (state === 'speaking' ? 0.55 : 0.8));
      break;
    case 'message':
      onMessage(ev.kind, String(ev.text || ''), ev.ts);
      break;
    case 'speech':
      setSubtitle(ev.text || '');
      typing(ev.text || '');
      break;
    default:
      break;
  }
}

function onStats(raw) {
  const s = parse(raw);
  if (!s) return;
  els.modelText.textContent = s.online ? s.model : 'ollama не запущена';
  els.modelPill.className = `pill ${s.online ? 'ok' : 'bad'}`;
  els.cpu.textContent = `${Math.round(s.cpu ?? 0)}%`;
  els.ram.textContent = `${Math.round(s.ram ?? 0)}%`;
  els.voice.textContent = s.voice || '—';
  if (typeof s.muted === 'boolean' && s.muted !== muted) applyMuted(s.muted, false);
}

function applyMuted(value, notify = true) {
  muted = value;
  els.mic.classList.toggle('is-on', !muted);
  els.mic.classList.toggle('is-off', muted);
  els.mic.setAttribute('aria-pressed', String(!muted));
  if (notify) link?.setMuted(muted);
  setState(state);
}

/* ------------------------------------------------------------------ ввод */

function send(text) {
  const clean = text.trim();
  if (!clean || !link) return;
  link.sendText(clean);
  els.input.value = '';
  autosize();
}

function autosize() {
  els.input.style.height = 'auto';
  els.input.style.height = `${Math.min(160, els.input.scrollHeight)}px`;
}

els.composer.addEventListener('submit', (e) => { e.preventDefault(); send(els.input.value); });
els.input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(els.input.value); }
});
els.input.addEventListener('input', autosize);
document.querySelectorAll('#suggest .chip').forEach((chip) => chip.addEventListener('click', () => send(chip.textContent)));
$('call').addEventListener('click', () => link?.startCall());
$('stop').addEventListener('click', () => link?.interrupt());
$('reset').addEventListener('click', () => {
  link?.reset();
  els.list.innerHTML = '';
  count = 0; turn = null;
  els.empty.hidden = false;
  els.counter.textContent = 'новый разговор';
  orb?.pulse(1);
});
els.mic.addEventListener('click', () => applyMuted(!muted));
$('expand').addEventListener('click', (e) => {
  els.hub.classList.toggle('show-steps');
  e.currentTarget.classList.toggle('is-on');
});
wireCopy(els.list, (text) => link?.copyText(text));
document.addEventListener('visibilitychange', () => orb?.pause(document.hidden));

/* ------------------------------------------------------------------ запуск */

connect(SIGNALS, SLOTS).then((created) => {
  link = created;
  link.event.connect(onEvent);
  link.stats.connect(onStats);
  link.history.connect((raw) => {
    const items = parse(raw) || [];
    items.forEach((ev) => { if (ev.kind !== 'system') onMessage(ev.kind, String(ev.text || ''), ev.ts, false); });
  });
  link.ready();
  setState('idle');
}).catch((err) => {
  els.stateText.textContent = 'нет связи';
  console.error(err);
});
