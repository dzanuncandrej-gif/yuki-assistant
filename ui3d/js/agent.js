/**
 * Вкладка «Агент»: события агента-программиста превращаются в конвейер этапов,
 * план с галочками, журнал, вкладки файлов с живым кодом и терминал проверок.
 */

import { connect, escapeHtml, parse } from './link.js';
import { highlight, languageOf } from './highlight.js';

const SIGNALS = ['event', 'recent', 'project'];
const SLOTS = ['ready', 'create', 'change', 'stop', 'openFolder', 'openEditor', 'run', 'loadProject', 'copyText'];

const STAGES = [
  { id: 'plan', name: 'План', icon: '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>' },
  { id: 'code', name: 'Код', icon: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/>' },
  { id: 'test', name: 'Тесты и робот', icon: '<path d="M9 3h6M10 3v6L4.5 18.5A1.6 1.6 0 0 0 6 21h12a1.6 1.6 0 0 0 1.5-2.5L14 9V3"/>' },
  { id: 'review', name: 'Ревью', icon: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>' },
  { id: 'done', name: 'Готово', icon: '<path d="M5 12l5 5 9-10"/>' },
];
const IDEAS = [
  ['Игра', 'змейка с рекордом, паузой и ускорением'],
  ['Калькулятор', 'с историей вычислений и вводом с клавиатуры'],
  ['Сайт', 'портфолио с тёмной темой и анимациями'],
  ['Список дел', 'с приоритетами, поиском и сохранением'],
  ['Игра', 'тетрис с уровнями и рекордом'],
  ['Таймер', 'помодоро с историей сессий'],
  ['Конвертер', 'единиц: длина, вес, температура'],
];
const KIND_NAMES = { gui: 'программа с окном', game: 'игра', console: 'консольная программа', web: 'сайт' };

const $ = (id) => document.getElementById(id);
let link = null;
let orb = null;
const files = new Map();      // путь → содержимое
const writing = new Map();    // путь → текст, который модель пишет прямо сейчас
let current = '';
let root = '';
let busy = false;
let startedAt = 0;
let timerId = 0;
let speedChars = 0;
let speedSince = 0;
let stageTimes = {};
let changeMode = false;
let lastProject = null;

// ---------------------------------------------------------------- построение

function buildStages() {
  $('stages').innerHTML = STAGES.map((stage) => `
    <li class="stage" id="stage-${stage.id}">
      <span class="stage__dot"><svg viewBox="0 0 24 24">${stage.icon}</svg></span>
      <span class="stage__name">${stage.name}</span>
      <span class="stage__time" id="stage-time-${stage.id}"></span>
    </li>`).join('');
}

function buildChips() {
  $('chips').innerHTML = IDEAS.map(([head, tail], index) =>
    `<button class="chip" type="button" role="listitem" data-index="${index}"><b>${escapeHtml(head)}</b>${escapeHtml(tail)}</button>`).join('');
  $('chips').addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (!chip) return;
    const [head, tail] = IDEAS[Number(chip.dataset.index)];
    setMode(false);
    $('task').value = `${head} ${tail}`.replace(/^Игра /, 'Игра ');
    autosize();
    $('task').focus();
  });
}

function autosize() {
  const area = $('task');
  area.style.height = 'auto';
  area.style.height = `${Math.min(96, area.scrollHeight)}px`;
}

function setMode(change) {
  changeMode = Boolean(change && root);
  $('mode').hidden = !root;
  $('mode').textContent = changeMode ? `доработка: ${lastProject || 'проект'}` : 'новый проект';
  $('mode').style.cursor = 'pointer';
  $('create-label').textContent = changeMode ? 'Доработать' : 'Создать';
  $('task').placeholder = changeMode
    ? 'Что изменить? Например: добавь тёмную тему и звук при нажатии'
    : 'Опиши программу — например, игра змейка с рекордом и паузой';
}

// ---------------------------------------------------------------- этапы и время

function stage(id, status) {
  const node = $(`stage-${id}`);
  if (!node) return;
  node.classList.remove('run', 'ok', 'fail');
  node.classList.add(status);
  if (status === 'run') stageTimes[id] = performance.now();
  else if (stageTimes[id]) $(`stage-time-${id}`).textContent = clock((performance.now() - stageTimes[id]) / 1000);
  const index = STAGES.findIndex((item) => item.id === id);
  const done = STAGES.filter((item) => $(`stage-${item.id}`).classList.contains('ok')).length;
  $('speed-bar').style.width = `${Math.max(done, status === 'run' ? index + 0.5 : done) / STAGES.length * 100}%`;
}

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

function tick() {
  if (busy) $('timer').textContent = clock((performance.now() - startedAt) / 1000);
  const span = (performance.now() - speedSince) / 1000;
  if (busy && span > 1.5) {
    // ~3.2 знака кода на токен — грубая, но честная оценка скорости модели
    const rate = speedChars / 3.2 / span;
    $('speed').textContent = rate > 0.5 ? `модель пишет · ~${rate.toFixed(0)} ток/с` : 'модель думает…';
    speedChars = 0;
    speedSince = performance.now();
  }
}

// ---------------------------------------------------------------- журнал и план

function log(text, status = 'ok') {
  const list = $('log');
  const lastItem = list.lastElementChild;
  if (lastItem && lastItem.classList.contains('run') && status !== 'run') lastItem.remove();
  const item = document.createElement('li');
  item.className = status;
  item.innerHTML = `<i></i><span>${escapeHtml(text)}</span><time>${$('timer').textContent}</time>`;
  list.appendChild(item);
  while (list.children.length > 60) list.firstElementChild.remove();
  list.scrollTop = list.scrollHeight;
}

function showPlan(plan) {
  const features = plan?.features || [];
  $('features').innerHTML = features.length
    ? features.map((item) => `<li>${escapeHtml(item)}</li>`).join('')
    : '<li class="empty">План без списка функций</li>';
  $('feature-count').textContent = features.length ? `0 / ${features.length}` : '—';
  $('project-kind').textContent = KIND_NAMES[plan?.kind] || 'проект';
}

function markFeatures(missing = []) {
  const items = [...$('features').querySelectorAll('li:not(.empty)')];
  const lost = missing.map((text) => text.toLowerCase().slice(0, 18));
  let done = 0;
  items.forEach((item) => {
    const miss = lost.some((part) => item.textContent.toLowerCase().includes(part.slice(0, 12)));
    item.classList.toggle('missing', miss);
    item.classList.toggle('done', !miss);
    if (!miss) done += 1;
  });
  if (items.length) $('feature-count').textContent = `${done} / ${items.length}`;
}

// ---------------------------------------------------------------- вкладки и код

function tab(path) {
  let node = [...$('tabs').children].find((item) => item.dataset.path === path);
  if (!node) {
    node = document.createElement('button');
    node.className = 'tab';
    node.type = 'button';
    node.setAttribute('role', 'tab');
    node.dataset.path = path;
    node.innerHTML = `<i class="${languageOf(path)}"></i><span>${escapeHtml(path || 'правка')}</span><small></small>`;
    node.addEventListener('click', () => select(path));
    $('tabs').appendChild(node);
  }
  return node;
}

function select(path) {
  current = path;
  [...$('tabs').children].forEach((item) => item.setAttribute('aria-selected', String(item.dataset.path === path)));
  render(false);
}

function stripFence(text) {
  return text.replace(/^[\s\S]*?```[\w+#.-]*[ \t]*\n/, (head) => (head.includes('```') ? '' : head)).replace(/\n```[\s\S]*$/, '');
}

function render(fresh) {
  const live = writing.has(current);
  const text = live ? stripFence(writing.get(current)) : files.get(current) ?? '';
  const view = $('code');
  const stick = view.scrollTop + view.clientHeight >= view.scrollHeight - 40;
  const lines = highlight(text, languageOf(current));
  const old = $('code-lines').children.length;
  $('code-lines').innerHTML = lines.map((html, index) =>
    `<span class="line${fresh && index >= old - 1 ? ' fresh' : ''}">${html || ' '}</span>`).join('')
    + (live ? '<span class="line"><span class="caret"></span></span>' : '');
  showCode(true);
  if (live && stick) view.scrollTop = view.scrollHeight;
  const node = tab(current);
  node.querySelector('small').textContent = text ? `${text.split('\n').length}` : '';
}

function showCode(visible) {
  $('code').hidden = !visible;
  $('empty').hidden = visible;
  orb?.pause(visible);
}

// ---------------------------------------------------------------- терминал

function terminal(title, ok, output) {
  const out = $('terminal-out');
  out.insertAdjacentHTML('beforeend',
    `<div class="head ${ok ? 'ok' : 'fail'}">${ok ? '✓' : '✕'} ${escapeHtml(title)}</div>`
    + (output ? `<div>${escapeHtml(output.trim())}</div>` : ''));
  out.scrollTop = out.scrollHeight;
  const summary = $('terminal-summary');
  summary.textContent = `${ok ? '✓' : '✕'} ${title}`;
  summary.className = `mono ${ok ? 'ok' : 'fail'}`;
  if (!ok) openTerminal(true);
}

function openTerminal(open) {
  $('terminal').classList.toggle('open', open);
  $('terminal-toggle').setAttribute('aria-expanded', String(open));
}

// ---------------------------------------------------------------- события агента

function reset(task, mode) {
  busy = true;
  startedAt = performance.now();
  speedSince = startedAt;
  speedChars = 0;
  stageTimes = {};
  buildStages();
  $('log').innerHTML = '';
  $('terminal-out').innerHTML = '';
  $('terminal-summary').textContent = 'проверок ещё не было';
  $('terminal-summary').className = 'mono';
  openTerminal(false);
  writing.clear();
  if (mode !== 'change') {
    files.clear();
    $('tabs').innerHTML = '';
    $('features').innerHTML = '<li class="empty">Юки продумывает функции…</li>';
    $('project-title').textContent = 'Проектирую…';
  }
  $('stop').hidden = false;
  $('create').disabled = true;
  $('agent').classList.add('busy');
  if (task && !$('task').value) $('task').value = task;
}

function onEvent(raw) {
  const event = parse(raw);
  if (!event || event.type !== 'coder') return;
  switch (event.event) {
    case 'start':
      reset(event.text, event.mode);
      log(event.mode === 'change' ? 'Доработка проекта' : 'Новый проект', 'ok');
      break;
    case 'stage':
      stage(event.stage, event.status);
      break;
    case 'plan':
      root = event.root || root;
      lastProject = event.title;
      $('project-title').textContent = event.title || 'Проект';
      showPlan(event.plan);
      ['run', 'folder', 'editor'].forEach((id) => { $(id).disabled = false; });
      break;
    case 'step':
      log(event.text, event.status || 'ok');
      break;
    case 'stream': {
      const path = event.path || '';
      speedChars += (event.text || '').length;
      writing.set(path, (writing.get(path) || '') + (event.text || ''));
      tab(path).classList.add('writing');
      if (current !== path) select(path);
      else render(false);
      break;
    }
    case 'stream_reset':
      writing.delete(event.path || '');
      if (current === (event.path || '')) render(false);
      break;
    case 'file':
      writing.delete(event.path);
      if (writing.has('')) writing.delete('');
      [...$('tabs').children].filter((item) => item.dataset.path === '').forEach((item) => item.remove());
      files.set(event.path, event.content || '');
      tab(event.path).classList.remove('writing');
      if (current === event.path || current === '' || !files.has(current)) select(event.path);
      else render(true);
      break;
    case 'check':
      terminal(event.text, event.ok, event.output || '');
      break;
    case 'review':
      markFeatures(event.missing || []);
      if (event.notes) log(`Ревью: ${event.notes}`, 'ok');
      break;
    case 'done':
      busy = false;
      tick();
      log(event.text, event.ok ? 'ok' : 'fail');
      if (event.ok) { stage('done', 'ok'); if (!$('features').querySelector('.done, .missing')) markFeatures([]); }
      $('speed').textContent = event.ok ? `готово за ${clock(event.seconds || 0)}` : 'остановилась на ошибке';
      $('stop').hidden = true;
      $('create').disabled = false;
      $('agent').classList.remove('busy');
      writing.clear();
      [...$('tabs').children].forEach((item) => item.classList.remove('writing'));
      if (event.root) root = event.root;
      $('task').value = '';
      setMode(Boolean(event.ok));
      link?.ready?.();
      break;
    default:
  }
}

function onRecent(raw) {
  const items = parse(raw) || [];
  $('recent').innerHTML = items.length
    ? items.slice(0, 8).map((item) => `
      <li><button type="button" data-root="${escapeHtml(item.root)}" title="${escapeHtml(item.root)}">
        <i class="${item.ok ? '' : 'fail'}"></i><span>${escapeHtml(item.title)}</span>
        <small>${escapeHtml(KIND_NAMES[item.kind] || '')}</small></button></li>`).join('')
    : '<li class="empty">Здесь появятся твои проекты</li>';
}

function onProject(raw) {
  const project = parse(raw);
  if (!project) return;
  files.clear();
  $('tabs').innerHTML = '';
  root = project.root;
  lastProject = project.title;
  $('project-title').textContent = project.title;
  showPlan(project.plan);
  markFeatures([]);
  buildStages();
  Object.entries(project.files || {}).forEach(([path, body]) => { files.set(path, body); tab(path); });
  const first = project.plan?.entry && files.has(project.plan.entry) ? project.plan.entry : [...files.keys()][0];
  if (first) select(first);
  ['run', 'folder', 'editor'].forEach((id) => { $(id).disabled = false; });
  setMode(true);
}

// ---------------------------------------------------------------- запуск

async function main() {
  buildStages();
  buildChips();
  setMode(false);
  try {
    const { createOrb } = await import('./orb.js');
    orb = createOrb($('orb'), { count: 16000, zoom: 12.5, size: 1.2 });
    orb.place(0, 0.35, 0.82);
    orb.mode('thinking');
    orb.setFps?.(40);
  } catch (err) {
    console.warn('WebGL недоступен', err);
  }

  link = await connect(SIGNALS, SLOTS);
  link.event.connect(onEvent);
  link.recent.connect(onRecent);
  link.project.connect(onProject);

  $('prompt').addEventListener('submit', (event) => {
    event.preventDefault();
    const task = $('task').value.trim();
    if (!task || busy) { $('task').focus(); return; }
    if (changeMode) link.change(task); else link.create(task);
  });
  $('task').addEventListener('input', autosize);
  $('task').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || !event.shiftKey)) { event.preventDefault(); $('prompt').requestSubmit(); }
  });
  $('mode').addEventListener('click', () => setMode(!changeMode));
  $('stop').addEventListener('click', () => link.stop());
  $('folder').addEventListener('click', () => link.openFolder(root));
  $('editor').addEventListener('click', () => link.openEditor(root));
  $('run').addEventListener('click', () => link.run(root));
  $('copy').addEventListener('click', () => {
    const text = files.get(current);
    if (!text) return;
    link.copyText(text);
    $('copy').classList.add('done');
    setTimeout(() => $('copy').classList.remove('done'), 1200);
  });
  $('recent').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-root]');
    if (button && !busy) link.loadProject(button.dataset.root);
  });
  $('terminal-toggle').addEventListener('click', () => openTerminal(!$('terminal').classList.contains('open')));
  timerId = setInterval(tick, 500);
  link.ready();
}

main();
window.addEventListener('beforeunload', () => clearInterval(timerId));
