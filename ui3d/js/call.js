/**
 * Окно видеосвязи. Кадры экрана и камеры питон присылает сам, когда они
 * меняются, — страница ничего не опрашивает и очередь картинок не копит.
 */
import { connect, escapeHtml, parse } from './link.js';
import { createOrb } from './orb.js';

const SIGNALS = ['event', 'stats', 'screenFrame', 'cameraFrame', 'layout'];
const SLOTS = ['ready', 'hangup', 'setMuted', 'interrupt', 'toggleMini', 'escape', 'ask', 'startDrag'];

const STATE_TEXT = { idle: 'на связи', listening: 'слушаю', thinking: 'думаю', speaking: 'говорю', acting: 'действую', muted: 'микрофон выкл' };
const GESTURES = { point: '☝ пауза / play', ok: '👌 громкость', peace: '✌ следующий', palm: '✋ тишина', fist: '✊ микрофон', three: '🤟 компаньон', volume: '👌 громкость' };

const $ = (id) => document.getElementById(id);
const root = $('call');
const els = {
  timer: $('timer'), statePill: $('state-pill'), stateText: $('state-text'),
  visionPill: $('vision-pill'), visionText: $('vision-text'), cameraPill: $('camera-pill'), cameraText: $('camera-text'),
  screen: $('screen'), screenEmpty: $('screen-empty'), screenMeta: $('screen-meta'), caption: $('caption'),
  camera: $('camera'), cameraEmpty: $('camera-empty'), face: $('face'), gesture: $('gesture'),
  lines: $('lines'), you: $('you'), yuki: $('yuki'), mic: $('mic'),
};

let orb = null;
try {
  orb = createOrb(document.querySelector('.gl'), { count: 46000, zoom: 11, size: 1.5 });
  orb.mode('greeting');
  setTimeout(() => orb.mode('idle'), 1600);
} catch (err) {
  console.warn('WebGL недоступен', err);
}

let link = null;
let state = 'idle';
let muted = false;
let mini = false;
const started = Date.now();
let youTimer = 0;
let yukiTimer = 0;
let gestureTimer = 0;

function place() {
  if (!orb) return;
  if (mini) orb.place(0, 0.08, 0.8);
  else if (window.innerWidth < 900) orb.place(0, 0.08, 0.95);
  else orb.place(-0.24, 0.06, 0.8);
}
place();
window.addEventListener('resize', place);

setInterval(() => {
  const s = Math.floor((Date.now() - started) / 1000);
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  els.timer.textContent = h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}, 1000);

function orbMode(name) {
  if (muted && name !== 'speaking') return 'muted';
  return { acting: 'acting', thinking: 'thinking', speaking: 'speaking', listening: 'idle' }[name] || 'idle';
}

const STATE_FPS = { thinking: 60, acting: 60, speaking: 60, listening: 60, idle: 60, muted: 60 };

function setState(name) {
  state = name;
  orb?.setFps(STATE_FPS[name] || 60);
  const shown = muted && name !== 'speaking' ? 'muted' : name;
  els.statePill.dataset.state = shown;
  els.stateText.textContent = STATE_TEXT[shown] || name;
  orb?.mode(orbMode(name));
}

function line(kind, text) {
  if (!text.trim()) return;
  const li = document.createElement('li');
  li.className = kind;
  li.innerHTML = kind === 'sys' ? escapeHtml(text) : `<b>${kind === 'yuki' ? 'ЮКИ' : 'ТЫ'}</b>${escapeHtml(text)}`;
  els.lines.append(li);
  while (els.lines.children.length > 60) els.lines.firstChild.remove();
  els.lines.scrollTop = els.lines.scrollHeight;
}

function show(el, text, ms, timerKey) {
  el.textContent = text;
  el.style.opacity = 1;
  if (timerKey === 'you') { clearTimeout(youTimer); youTimer = setTimeout(() => { el.style.opacity = 0; }, ms); }
  else { clearTimeout(yukiTimer); yukiTimer = setTimeout(() => { el.style.opacity = 0; }, ms); }
}

function onEvent(raw) {
  const ev = parse(raw);
  if (!ev) return;
  if (ev.type === 'state') {
    if (!(state === 'acting' && ev.state === 'thinking')) setState(ev.state);
    if (orb) orb.target.amp = 0;
  } else if (ev.type === 'level') {
    if (orb) orb.target.amp = Math.min(0.6, (ev.level || 0) * (state === 'speaking' ? 0.55 : 0.45));
  } else if (ev.type === 'speech') {
    show(els.yuki, ev.text || '', 7000, 'yuki');
  } else if (ev.type === 'vision') {
    const text = String(ev.caption || '');
    if (text) {
      els.caption.textContent = text;
      els.caption.classList.toggle('is-trouble', /ошибк|error|failed|не удалось|warning|предупрежд/i.test(text));
      orb?.pulse(0.25);
    }
  } else if (ev.type === 'message') {
    const text = String(ev.text || '');
    if (ev.kind === 'user') { show(els.you, `«${text}»`, 5000, 'you'); line('you', text); }
    else if (ev.kind === 'assistant') line('yuki', text);
    else if (ev.kind === 'report') line('yuki', text.split('\n')[0]);
    else if (ev.kind === 'error') line('sys', `ошибка: ${text}`);
    else if (ev.kind === 'system' && text.startsWith('→')) { setState('acting'); line('sys', text); }
  }
}

function pill(el, textEl, ok, text) {
  el.className = `pill ${ok === null ? '' : ok ? 'ok' : 'warn'}`;
  textEl.textContent = text;
}

function onStats(raw) {
  const s = parse(raw);
  if (!s) return;
  if (s.vision) {
    pill(els.visionPill, els.visionText, s.vision.healthy, s.vision.fps ? `экран ${Math.round(s.vision.fps)} к/с` : 'экран');
    els.screenMeta.textContent = s.vision.analysis || '—';
  }
  if (s.camera) {
    const c = s.camera;
    if (c.error) pill(els.cameraPill, els.cameraText, false, 'камера недоступна');
    else pill(els.cameraPill, els.cameraText, c.present ? true : null, c.present ? (c.identity ? `вижу: ${c.identity}` : 'вижу тебя') : 'никого');
    els.face.textContent = c.identity || (c.present ? `людей: ${c.people}` : 'нет лица');
    els.cameraEmpty.textContent = c.error ? 'камера недоступна' : 'камера включается…';
    if (c.gesture && GESTURES[c.gesture]) {
      els.gesture.textContent = GESTURES[c.gesture];
      els.gesture.hidden = false;
      clearTimeout(gestureTimer);
      gestureTimer = setTimeout(() => { els.gesture.hidden = true; }, 1400);
    }
  } else {
    pill(els.cameraPill, els.cameraText, null, 'камера выкл');
    els.cameraEmpty.textContent = 'камера выключена в настройках';
  }
  if (typeof s.muted === 'boolean' && s.muted !== muted) applyMuted(s.muted, false);
}

function frame(img, empty, data) {
  if (!data) return;
  img.src = `data:image/jpeg;base64,${data}`;
  img.classList.add('is-live');
  empty.hidden = true;
}

function applyMuted(value, notify = true) {
  muted = value;
  els.mic.classList.toggle('is-on', !muted);
  els.mic.classList.toggle('is-off', muted);
  els.mic.setAttribute('aria-pressed', String(!muted));
  if (notify) link?.setMuted(muted);
  setState(state);
}

function setMini(value) {
  mini = value;
  root.classList.toggle('mini', mini);
  place();
}

$('mic').addEventListener('click', () => applyMuted(!muted));
$('stop').addEventListener('click', () => link?.interrupt());
$('look').addEventListener('click', () => link?.ask('Что ты видишь на экране?'));
$('mini').addEventListener('click', () => link?.toggleMini());
$('hangup').addEventListener('click', () => { orb?.pulse(1); link?.hangup(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { e.preventDefault(); link?.escape(); }
  if (e.ctrlKey && (e.key === 'm' || e.key === 'ь')) { e.preventDefault(); link?.toggleMini(); }
});
// окошко без рамки перетаскивается за любое пустое место
root.addEventListener('mousedown', (e) => {
  if (!mini || e.button !== 0 || e.target.closest('button')) return;
  link?.startDrag();
});
root.addEventListener('dblclick', (e) => { if (!e.target.closest('button')) link?.toggleMini(); });

connect(SIGNALS, SLOTS).then((created) => {
  link = created;
  link.event.connect(onEvent);
  link.stats.connect(onStats);
  link.screenFrame.connect((data) => frame(els.screen, els.screenEmpty, data));
  link.cameraFrame.connect((data) => frame(els.camera, els.cameraEmpty, data));
  link.layout.connect((name) => setMini(name === 'mini'));
  link.ready();
  setState('idle');
  line('sys', 'звонок начат — говори без обращения по имени');
}).catch((err) => { els.stateText.textContent = 'нет связи'; console.error(err); });
