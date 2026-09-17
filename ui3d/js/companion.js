/**
 * Экранный компаньон: сборка сцены, персонажа и «мозга» в одно живое существо.
 *
 * Страница показывается внутри прозрачного окна на рабочем столе. Фона нет —
 * видна только фигура и её свечение, всё остальное рисует Qt под ней.
 */

import * as THREE from 'three';
import { Stage, ACCENT } from './stage.js';
import { Character } from './character.js';
import { Behaviour } from './behaviour.js';
import { connect } from './bridge.js';

const ROOT = './characters';
const FALLBACK = 'lacrimosa';

const canvas = document.getElementById('view');
const status = document.getElementById('status');

let link = null;
let stage = null;
let character = null;
let brain = null;
let loading = false;
let elapsed = 0;
let settings = {};

const report = (text, fatal = false) => {
  if (status) {
    status.textContent = text || '';
    status.classList.toggle('fatal', fatal);
    status.classList.toggle('hidden', !text);
  }
  if (fatal && link && link.onError) link.onError(String(text));
};

// ---------------------------------------------------------------- загрузка

async function loadCharacter(id) {
  if (loading) return;
  loading = true;
  const key = id || FALLBACK;
  report('Загружаю персонажа…');
  try {
    const manifest = await (await fetch(`${ROOT}/${key}/avatar.json`)).json();
    const next = new Character(manifest, `${ROOT}/${key}`);
    await next.load((share) => report(`Загружаю персонажа… ${Math.round(share * 100)}%`));

    if (character) {
      stage.scene.remove(character.root);
      character.dispose();
    }
    character = next;
    stage.scene.add(character.root);
    stage.watch(character.root);
    brain = new Behaviour(character);
    applySettings(settings);
    brain.react('greet');
    report('');
    if (link && link.onReady) {
      link.onReady({ character: key, morphs: character.morphNames().length });
    }
  } catch (error) {
    report(`Персонаж не загрузился: ${error.message}`, true);
  } finally {
    loading = false;
  }
}

// ---------------------------------------------------------------- настройки

function applySettings(next) {
  settings = { ...settings, ...(next || {}) };
  if (!stage) return;

  // размер задаётся приближением камеры, а не масштабом модели: иначе кадр
  // пересчитывается по новым габаритам и фигура остаётся того же размера
  stage.setFraming(settings.framing || 'full', Number(settings.scale ?? 1));
  stage.setQuality(settings.quality || 'high');
  if (settings.accent) stage.setAccent(settings.accent);
  if (brain) brain.lipSync = settings.lip_sync !== false;
  if (brain && settings.follow_cursor === false) brain.setPointer(0, 0, false);
  if (brain) brain.idleMotion = settings.idle_motion !== false;
}

// ---------------------------------------------------------------- события Qt

function wire() {
  link.stateChanged.connect((state) => {
    if (!brain) return;
    brain.setState(state);
    stage.setAccent(ACCENT[state] || ACCENT.idle);
  });
  link.levelChanged.connect((level) => { if (brain) brain.setLevel(level); });
  link.visemeChanged.connect((data) => {
    if (!brain || brain.lipSync === false) return;
    brain.setViseme(typeof data === 'string' ? JSON.parse(data) : data);
  });
  link.emotionRequested.connect((name, seconds) => { if (brain) brain.playEmotion(name, seconds); });
  link.gestureRequested.connect((name) => { if (brain) brain.playGesture(name); });
  link.reactRequested.connect((kind) => { if (brain) brain.react(kind); });
  link.settingsChanged.connect((data) => applySettings(typeof data === 'string' ? JSON.parse(data) : data));
  link.characterChanged.connect((id) => loadCharacter(id));
  link.pointerMoved.connect((x, y, active) => {
    if (brain && settings.follow_cursor !== false) brain.setPointer(x, y, active);
  });
}

// ---------------------------------------------------------------- ввод мышью

function wirePointer() {
  canvas.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    // окно тянут за саму фигуру: перетаскиванием занимается Qt, не страница
    if (link.onDragStart) link.onDragStart();
  });
  canvas.addEventListener('click', () => {
    if (link.onClick) link.onClick();
    if (brain) brain.playEmotion(Math.random() < 0.5 ? 'happy' : 'surprised', 2.2);
  });
  window.addEventListener('pointermove', (event) => {
    if (!brain || settings.follow_cursor === false) return;
    brain.setPointer((event.clientX / window.innerWidth) * 2 - 1,
                     (event.clientY / window.innerHeight) * 2 - 1, true);
  });
}

// ---------------------------------------------------------------- кадр

function loop() {
  const clock = new THREE.Clock();
  const frame = () => {
    const delta = Math.min(0.06, clock.getDelta());
    elapsed += delta;
    if (character) character.update(delta);
    if (brain) brain.update(delta, elapsed);
    stage.render(delta);
    requestAnimationFrame(frame);
  };
  frame();
}

// ---------------------------------------------------------------- старт

async function main() {
  window.addEventListener('error', (event) => report(event.message, true));
  window.addEventListener('unhandledrejection', (event) => report(String(event.reason), true));

  link = await connect();
  stage = new Stage(canvas, { transparent: true, quality: 'high' });
  wire();
  wirePointer();
  loop();

  const params = new URLSearchParams(window.location.search);
  await loadCharacter(params.get('character'));

  Object.assign(window, { stage, brain, character, applySettings, loadCharacter });
}

main();
