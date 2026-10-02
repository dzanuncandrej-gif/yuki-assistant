/**
 * Вкладка «Плейлист»: обложка и спектр слева, очередь с поиском справа.
 * Ядро из частиц дышит басами, полосы спектра — всем диапазоном.
 */

import { connect, escapeHtml, parse } from './link.js';

const SIGNALS = ['state', 'library', 'spectrum', 'progress'];
const SLOTS = ['ready', 'act'];
const $ = (id) => document.getElementById(id);

let link = null;
let orb = null;
let library = [];
let state = { playing: false, shuffle: false, repeat: 'all', volume: 0.6, path: '' };
let position = 0;
let duration = 0;
let filter = 'all';
let query = '';
let bands = new Array(32).fill(0);
let shown = new Array(32).fill(0);
let dragging = null;
let seeking = false;
let toastTimer = 0;

const clock = (ms) => {
  const seconds = Math.max(0, Math.floor((ms || 0) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
};

/** Цвета обложки-заглушки — стабильно из названия, чтобы у песни всегда был «свой» цвет. */
function hues(text) {
  let hash = 0;
  for (const char of String(text)) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
  return [hash % 360, (hash >> 9) % 360];
}

function fallback(track) {
  const [a, b] = hues(`${track.artist}${track.title}`);
  return `linear-gradient(135deg, hsl(${a} 85% 58%), hsl(${b} 80% 42%))`;
}

const initial = (track) => (track.title || '♪').trim().charAt(0).toUpperCase() || '♪';
const coverUrl = (track) => (track.cover ? `covers/${encodeURIComponent(track.cover)}` : '');

function toast(text) {
  const node = $('toast');
  node.textContent = text;
  node.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('on'), 2200);
}

// ---------------------------------------------------------------- сейчас играет

function current() {
  return library.find((track) => track.path === state.path) || null;
}

function renderNow() {
  const track = current();
  document.body.classList.toggle('playing', Boolean(state.playing));
  $('music').classList.toggle('playing', Boolean(state.playing));
  $('toggle').setAttribute('aria-label', state.playing ? 'Пауза' : 'Играть');
  $('toggle-icon').innerHTML = state.playing
    ? '<rect x="6.5" y="5" width="4" height="14" rx="1" class="fill"/><rect x="13.5" y="5" width="4" height="14" rx="1" class="fill"/>'
    : '<path d="M7 4.5v15l12.5-7.5z" class="fill"/>';
  $('shuffle').setAttribute('aria-pressed', String(Boolean(state.shuffle)));
  const repeatNames = { all: 'весь плейлист', one: 'одна песня', off: 'выключен' };
  $('repeat').classList.toggle('on', state.repeat !== 'off');
  $('repeat-one').hidden = state.repeat !== 'one';
  $('repeat').setAttribute('aria-label', `Повтор: ${repeatNames[state.repeat] || ''}`);
  $('repeat').title = `Повтор: ${repeatNames[state.repeat] || ''}`;
  if (document.activeElement !== $('volume')) $('volume').value = Math.round((state.volume ?? 0.6) * 100);

  if (!track) {
    $('now-title').textContent = 'Тишина';
    $('now-artist').textContent = library.length
      ? 'Выбери песню справа или скажи «Юки, включи мою музыку»'
      : 'Добавь песни справа — и говори «Юки, включи мою музыку»';
    $('now-meta').textContent = '';
    $('now-label').textContent = 'моя музыка';
    setCover(null);
    $('like').setAttribute('aria-pressed', 'false');
    orb?.mode('idle');
    return;
  }
  $('now-title').textContent = track.title;
  $('now-artist').textContent = [track.artist, track.album].filter(Boolean).join(' · ') || 'Неизвестный исполнитель';
  $('now-meta').textContent = `${track.plays ? `прослушано ${track.plays} раз` : 'первое прослушивание'}`
    + `${track.duration ? ` · ${clock(track.duration)}` : ''}`;
  $('now-label').textContent = state.playing ? 'сейчас играет' : 'на паузе';
  $('like').setAttribute('aria-pressed', String(Boolean(track.liked)));
  setCover(track);
  orb?.mode(state.playing ? 'speaking' : 'idle');
}

function setCover(track) {
  const image = $('cover-img');
  const url = track ? coverUrl(track) : '';
  $('cover').style.background = track ? fallback(track) : '';
  $('cover-letter').textContent = track ? initial(track) : '♪';
  image.hidden = !url;
  if (url && image.getAttribute('src') !== url) image.src = url;
  const backdrop = $('backdrop');
  backdrop.style.backgroundImage = url ? `url("${url}")` : (track ? fallback(track) : 'none');
  backdrop.classList.toggle('on', Boolean(track));
}

function renderProgress() {
  const share = duration ? Math.min(1, position / duration) : 0;
  $('bar-fill').style.width = `${share * 100}%`;
  $('bar-thumb').style.left = `${share * 100}%`;
  $('bar').setAttribute('aria-valuenow', String(Math.round(share * 100)));
  $('elapsed').textContent = clock(position);
  $('total').textContent = clock(duration);
}

// ---------------------------------------------------------------- очередь

function visible() {
  let items = library.map((track, index) => ({ ...track, index }));
  if (filter === 'liked') items = items.filter((track) => track.liked);
  if (filter === 'top') items = items.filter((track) => track.plays > 0).sort((a, b) => b.plays - a.plays);
  if (query) {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    items = items.filter((track) => {
      const text = `${track.title} ${track.artist} ${track.album}`.toLowerCase();
      return words.every((word) => text.includes(word));
    });
  }
  return items;
}

const HEART = '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-9.2-8.6C1.4 8.6 3 5 6.4 5c2 0 3.6 1.2 4.6 2.8h2C14 6.2 15.6 5 17.6 5 21 5 22.6 8.6 21.2 11.4 19 15.6 12 20 12 20z"/></svg>';
const CROSS = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';

function renderList() {
  const items = visible();
  const total = library.reduce((sum, track) => sum + (track.duration || 0), 0);
  $('stats').textContent = library.length
    ? `${library.length} ${plural(library.length, 'песня', 'песни', 'песен')}${total ? ` · ${clock(total)}` : ''}`
    : 'пока пусто';
  $('empty').hidden = library.length > 0;
  const reorder = filter === 'all' && !query;
  $('tracks').innerHTML = items.map((track) => {
    const isCurrent = track.path === state.path;
    const url = coverUrl(track);
    return `
      <li class="track${isCurrent ? ' current' : ''}${track.missing ? ' missing' : ''}${isCurrent && !state.playing ? ' paused' : ''}"
          data-path="${escapeHtml(track.path)}" draggable="${reorder}" tabindex="0"
          title="${escapeHtml(track.missing ? `Файл не найден: ${track.path}` : track.path)}">
        <span class="track__num">${isCurrent ? '<span class="eq"><i></i><i></i><i></i></span>' : track.index + 1}</span>
        <span class="thumb" style="background:${fallback(track)}">${url ? `<img src="${url}" alt="" loading="lazy">` : escapeHtml(initial(track))}</span>
        <span class="track__text">
          <span class="track__title">${escapeHtml(track.title)}</span>
          <span class="track__artist">${escapeHtml(track.artist || 'Неизвестный исполнитель')}</span>
        </span>
        <span class="track__time">${track.duration ? clock(track.duration) : ''}</span>
        <button class="row-btn like${track.liked ? ' liked' : ''}" type="button" data-act="like" aria-label="В любимые">${HEART}</button>
        <button class="row-btn remove" type="button" data-act="remove" aria-label="Убрать из плейлиста">${CROSS}</button>
      </li>`;
  }).join('') || (library.length ? '<li class="track"><span></span><span></span><span class="track__artist">Ничего не нашлось</span></li>' : '');
}

function plural(n, one, few, many) {
  const tail = n % 100;
  if (tail >= 11 && tail <= 14) return many;
  return n % 10 === 1 ? one : n % 10 >= 2 && n % 10 <= 4 ? few : many;
}

// ---------------------------------------------------------------- спектр

function drawSpectrum() {
  const canvas = $('spectrum');
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  const width = canvas.clientWidth * ratio;
  const height = canvas.clientHeight * ratio;
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, width, height);
  const count = shown.length;
  const gap = 4 * ratio;
  const barWidth = (width - gap * (count * 2 - 1)) / (count * 2);
  const gradient = context.createLinearGradient(0, height, 0, 0);
  gradient.addColorStop(0, 'rgba(88, 182, 255, 0.0)');
  gradient.addColorStop(0.35, 'rgba(88, 182, 255, 0.55)');
  gradient.addColorStop(1, 'rgba(164, 141, 255, 0.95)');
  context.fillStyle = gradient;
  for (let index = 0; index < count; index += 1) {
    shown[index] += (bands[index] - shown[index]) * 0.35;
    const value = shown[index];
    const barHeight = Math.max(2 * ratio, value * height * 0.92);
    // зеркально от центра: басы в середине, верхи по краям
    for (const side of [-1, 1]) {
      const x = width / 2 + side * (index * (barWidth + gap) + gap / 2) - (side < 0 ? barWidth : 0);
      context.beginPath();
      context.roundRect(x, height - barHeight, barWidth, barHeight, [barWidth / 2, barWidth / 2, 0, 0]);
      context.fill();
    }
  }
  if (orb) {
    const bass = (shown[0] + shown[1] + shown[2] + shown[3]) / 4;
    orb.target.amp = state.playing ? Math.min(1, bass * 1.4) : 0;
    if (bass > 0.72 && state.playing) orb.pulse(0.25);
  }
  requestAnimationFrame(drawSpectrum);
}

// ---------------------------------------------------------------- события

function onState(raw) {
  const data = parse(raw) || {};
  if ('dropping' in data) {
    $('drop').hidden = !data.dropping;
    if (data.added !== undefined) toast(data.added ? `Добавлено песен: ${data.added}` : 'Новых песен не нашлось');
    return;
  }
  const changed = data.path !== state.path || data.playing !== state.playing;
  state = { ...state, ...data };
  if (typeof data.duration === 'number' && data.duration > 0) duration = data.duration;
  renderNow();
  if (changed) renderList();
}

function onLibrary(raw) {
  const before = library.length;
  library = parse(raw) || [];
  renderList();
  renderNow();
  if (before && library.length > before) toast(`Добавлено песен: ${library.length - before}`);
}

function onProgress(pos, total) {
  if (seeking) return;
  position = pos;
  duration = total;
  renderProgress();
}

function onSpectrum(raw) {
  const data = parse(raw);
  if (Array.isArray(data)) bands = data;
}

// ---------------------------------------------------------------- взаимодействие

function seekTo(clientX) {
  const rect = $('bar').getBoundingClientRect();
  const share = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  position = share * duration;
  renderProgress();
  return position;
}

function wire() {
  const act = (action, argument = '') => link.act(action, String(argument));
  $('toggle').addEventListener('click', () => (library.length ? act('toggle') : act('add_files')));
  $('next').addEventListener('click', () => act('next'));
  $('prev').addEventListener('click', () => act('prev'));
  $('shuffle').addEventListener('click', () => act('shuffle', state.shuffle ? '0' : '1'));
  $('repeat').addEventListener('click', () => {
    const order = ['all', 'one', 'off'];
    act('repeat', order[(order.indexOf(state.repeat) + 1) % order.length]);
  });
  $('like').addEventListener('click', () => state.path && act('like', state.path));
  $('volume').addEventListener('input', (event) => act('volume', Number(event.target.value) / 100));
  $('add-files').addEventListener('click', () => act('add_files'));
  $('add-folder').addEventListener('click', () => act('add_folder'));

  const bar = $('bar');
  bar.addEventListener('pointerdown', (event) => {
    if (!duration) return;
    seeking = true;
    bar.classList.add('dragging');
    bar.setPointerCapture(event.pointerId);
    seekTo(event.clientX);
  });
  bar.addEventListener('pointermove', (event) => { if (seeking) seekTo(event.clientX); });
  bar.addEventListener('pointerup', (event) => {
    if (!seeking) return;
    seeking = false;
    bar.classList.remove('dragging');
    act('seek', Math.round(seekTo(event.clientX)));
  });
  bar.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      act('seek', Math.max(0, position + (event.key === 'ArrowRight' ? 5000 : -5000)));
    }
  });

  const list = $('tracks');
  list.addEventListener('click', (event) => {
    const row = event.target.closest('.track[data-path]');
    if (!row) return;
    const button = event.target.closest('[data-act]');
    if (button) { act(button.dataset.act, row.dataset.path); return; }
    if (row.dataset.path === state.path) act('toggle'); else act('play', row.dataset.path);
  });
  list.addEventListener('keydown', (event) => {
    const row = event.target.closest('.track[data-path]');
    if (!row) return;
    if (event.key === 'Enter') act('play', row.dataset.path);
    if (event.key === 'Delete') act('remove', row.dataset.path);
  });
  list.addEventListener('dragstart', (event) => {
    const row = event.target.closest('.track[data-path]');
    if (!row) return;
    dragging = row.dataset.path;
    row.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
  });
  list.addEventListener('dragover', (event) => {
    if (!dragging) return;
    event.preventDefault();
    list.querySelectorAll('.drop-before').forEach((node) => node.classList.remove('drop-before'));
    event.target.closest('.track[data-path]')?.classList.add('drop-before');
  });
  list.addEventListener('drop', (event) => {
    if (!dragging) return;
    event.preventDefault();
    const target = event.target.closest('.track[data-path]');
    const index = target ? library.findIndex((track) => track.path === target.dataset.path) : library.length;
    act('place', `${dragging}|${index}`);
  });
  list.addEventListener('dragend', () => {
    dragging = null;
    list.querySelectorAll('.dragging, .drop-before').forEach((node) => node.classList.remove('dragging', 'drop-before'));
  });

  $('search').addEventListener('input', (event) => { query = event.target.value.trim(); renderList(); });
  document.querySelectorAll('.filter').forEach((button) => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    document.querySelectorAll('.filter').forEach((item) => item.setAttribute('aria-selected', String(item === button)));
    renderList();
  }));

  document.addEventListener('keydown', (event) => {
    if (event.target.closest('input, textarea')) {
      if (event.key === 'Escape') event.target.blur();
      return;
    }
    if (event.code === 'Space') { event.preventDefault(); act('toggle'); }
    else if (event.key === 'ArrowRight' && event.shiftKey) act('next');
    else if (event.key === 'ArrowLeft' && event.shiftKey) act('prev');
    else if (event.key === 'ArrowRight') act('seek', position + 5000);
    else if (event.key === 'ArrowLeft') act('seek', Math.max(0, position - 5000));
    else if (event.key.toLowerCase() === 'l' || event.key.toLowerCase() === 'д') { if (state.path) act('like', state.path); }
    else if (event.key === '/') { event.preventDefault(); $('search').focus(); }
  });
}

async function main() {
  try {
    const { createOrb } = await import('./orb.js');
    orb = createOrb($('orb'), { count: 22000, zoom: 11.5, size: 1.25 });
    orb.place(0.55, 0.42, 0.85);
    orb.mode('idle');
  } catch (err) {
    console.warn('WebGL недоступен', err);
  }
  link = await connect(SIGNALS, SLOTS);
  link.state.connect(onState);
  link.library.connect(onLibrary);
  link.progress.connect(onProgress);
  link.spectrum.connect(onSpectrum);
  wire();
  renderNow();
  renderList();
  requestAnimationFrame(drawSpectrum);
  link.ready();
}

main();
