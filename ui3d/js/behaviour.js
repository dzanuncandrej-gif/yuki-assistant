/**
 * «Мозг» персонажа: то, что превращает модель в живого собеседника.
 *
 * Ни одна поза здесь не задана кадрами. Дыхание, моргание, взгляд, наклоны
 * головы и жесты считаются каждый кадр как сумма затухающих процессов, поэтому
 * повторов не возникает: два одинаковых вдоха подряд просто не выпадают.
 *
 * Поверх этого лежат состояния ассистента. Слушает — подаётся вперёд, смотрит в
 * камеру, чаще моргает. Думает — уводит взгляд вверх и в сторону, наклоняет
 * голову. Говорит — работает мимика и синхронизация губ. Ошибка — короткая
 * тревожная реакция, которая сама рассасывается.
 */

import * as THREE from 'three';

const clamp = (value, low = 0, high = 1) => (value < low ? low : (value > high ? high : value));
const lerp = (a, b, t) => a + (b - a) * t;
/** Экспоненциальное приближение, не зависящее от частоты кадров. */
const approach = (current, target, rate, delta) => lerp(current, target, 1 - Math.exp(-rate * delta));
const randomBetween = (low, high) => low + Math.random() * (high - low);

/** Сумма несоизмеримых синусов: похоже на живое дрожание, но без случайных скачков. */
function drift(time, seed, speed = 1) {
  return (
    Math.sin(time * 0.37 * speed + seed) * 0.55
    + Math.sin(time * 0.83 * speed + seed * 2.3) * 0.30
    + Math.sin(time * 1.71 * speed + seed * 4.1) * 0.15
  );
}

/**
 * Мимические наборы. Ключ — как называет эмоцию интерфейс, значение — какие
 * шейпы модели за неё отвечают: брови, веки и форма рта в этой эмоции.
 */
const EXPRESSIONS = {
  neutral: {},
  calm: { brow: 'EB_Serious_01', lid: 'EL_Serious_01', weight: 0.22 },
  attentive: { brow: 'EB_Surprised_01', lid: 'EL_Surprised_01', weight: 0.30, gain: 1.1 },
  thinking: { brow: 'EB_Thinking_01', lid: 'EL_Thinking_01', weight: 0.62 },
  doubt: { brow: 'EB_Doubt_01', lid: 'EL_Doubt_01', weight: 0.7 },
  smile: { brow: 'EB_Smile_01', lid: 'EL_Smile_01', weight: 0.55, mouth: 'jawOpen_Smile_01', mouthWeight: 0.35 },
  happy: { brow: 'EB_Happy_01', lid: 'EL_Happy_01', weight: 0.8, mouth: 'jawOpen_Happy_01', mouthWeight: 0.5 },
  surprised: { brow: 'EB_Surprised_01', lid: 'EL_Surprised_01', weight: 0.9, mouth: 'jawOpen_Surprised_01', mouthWeight: 0.55 },
  sad: { brow: 'EB_Sad_01', lid: 'EL_Sad_01', weight: 0.75, mouth: 'jawOpen_Sad_01', mouthWeight: 0.3 },
  serious: { brow: 'EB_Serious_01', lid: 'EL_Serious_01', weight: 0.7 },
  speechless: { brow: 'EB_Speechless_01', lid: 'EL_Speechless_01', weight: 0.7 },
  angry: { brow: 'EB_Angry_01', lid: 'EL_Angry_01', weight: 0.8, mouth: 'jawOpen_Angry_01', mouthWeight: 0.4 },
};

/** Состояние ассистента → как персонаж себя ведёт. */
const STATES = {
  idle: { expression: 'calm', energy: 0.75, lean: 0.0, gazeCamera: 0.35, blink: 1.0 },
  listening: { expression: 'attentive', energy: 1.05, lean: 0.06, gazeCamera: 0.95, blink: 1.25 },
  thinking: { expression: 'thinking', energy: 0.85, lean: -0.03, gazeCamera: 0.1, blink: 0.8 },
  speaking: { expression: 'smile', energy: 1.15, lean: 0.03, gazeCamera: 0.8, blink: 1.0 },
  success: { expression: 'happy', energy: 1.3, lean: 0.05, gazeCamera: 1.0, blink: 1.1 },
  error: { expression: 'sad', energy: 0.9, lean: -0.05, gazeCamera: 0.6, blink: 1.4 },
};

/** Короткие декоративные шейпы: аниме-приёмы, которыми реакция читается мгновенно. */
const DECALS = {
  blush: 'TDS_lianhong',
  shy: 'TDS_haixiu',
  stars: 'TDS_StarEyes',
  sweat: 'TD_Sweaty',
  dots: 'TDS_shengluehao_01',
  amazed: 'TD_Amazed',
  veins: 'TD_Veins',
};

/** Жесты: добавка к позе рук поверх базовой анимации, в радианах. */
const GESTURES = {
  // клип — кусок запечённой анимации модели, поза — процедурная добавка к рукам
  greet: { duration: 4.2, clip: 'flourish', head: { roll: 0.06 } },
  present: { duration: 4.2, clip: 'flourish' },
  aside: { duration: 3.8, clip: 'aside' },
  nod: { duration: 1.1, head: { pitch: 0.16, cycles: 2 } },
  tilt: { duration: 2.0, head: { roll: 0.14 } },
  shrug: {
    duration: 1.6,
    pose: { clavicleL: [0, 0, 0.16], clavicleR: [0, 0, -0.16], armL: [0, 0, 0.2], armR: [0, 0, -0.2] },
  },
  think: {
    duration: 2.6,
    pose: { clavicleR: [0, 0, -0.2], armR: [-0.75, 0.05, -0.55], foreR: [-0.2, -1.15, -0.15], handR: [0.2, 0, 0.1] },
    head: { roll: 0.1, pitch: -0.05 },
  },
};

const AXES = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)];

export class Behaviour {
  constructor(character) {
    this.character = character;
    this.state = 'idle';
    this.params = { ...STATES.idle };
    this.time = 0;

    // выключатели из меню: дыхание с микродвижениями и синхронизация рта
    this.idleMotion = true;
    this.lipSync = true;

    // мимика: текущее и целевое значение по каждому набору
    this.expression = 'calm';
    this.expressionWeight = 0;
    this.overlay = null;          // короткая эмоция поверх состояния
    this.overlayLeft = 0;
    this.weights = new Map();

    this.decals = new Map();      // имя шейпа → { value, target, left }

    this.blink = 0;
    this.blinkTimer = randomBetween(1.5, 4.0);
    this.blinkPhase = 'idle';
    this.blinkQueue = 0;

    this.gaze = new THREE.Vector2(0, 0);
    this.gazeTarget = new THREE.Vector2(0, 0);
    this.gazeTimer = 0;
    this.pointer = new THREE.Vector2(0, 0);
    this.pointerActive = false;

    this.head = { pitch: 0, yaw: 0, roll: 0 };
    this.headTarget = { pitch: 0, yaw: 0, roll: 0 };
    this.breath = 0;
    this.lean = 0;
    this.sway = 0;
    this.energy = 1;

    this.gesture = null;
    this.gestureTime = 0;
    this.gestureWeight = 0;

    this.viseme = { open: 0, a: 0, e: 0, i: 0, o: 0, u: 0 };
    this.visemeTarget = { open: 0, a: 0, e: 0, i: 0, o: 0, u: 0 };
    this.level = 0;
    // сглаженная громкость. Сырая приходит с каждым блоком звука, скачет от
    // 0.1 до 0.7 и обратно двадцать пять раз в секунду — подавать её прямо в
    // поворот головы нельзя, начинается дрожь
    this.levelSmooth = 0;
    // вклад жеста в наклон головы: обнуляется, когда жеста нет
    this.gestureHead = { pitch: 0, roll: 0 };
    this.speakingSince = 0;

    this._quaternion = new THREE.Quaternion();
    this._temp = new THREE.Quaternion();
  }

  // -------------------------------------------------------------- вход извне

  setState(state) {
    const next = STATES[state] ? state : 'idle';
    if (next === this.state) return;
    this.state = next;
    this.params = { ...STATES[next] };
    this.expression = this.params.expression;

    if (next === 'thinking') {
      this.gazeTarget.set(randomBetween(-0.75, -0.35) * (Math.random() < 0.5 ? 1 : -1), 0.55);
      this.gazeTimer = randomBetween(1.4, 2.6);
      const roll = Math.random();
      if (roll < 0.18) this.playGesture('aside');       // изредка отворачивается, будто вспоминает
      else if (roll < 0.6) this.playGesture('think');
      this.pulseDecal('dots', 0.45, 2.2);
    }
    if (next === 'listening') {
      this.gazeTarget.set(0, 0);
      this.gazeTimer = randomBetween(1.8, 3.2);
      if (Math.random() < 0.3) this.playGesture('nod');
    }
    if (next === 'speaking') this.speakingSince = this.time;
  }

  /** Короткая эмоция поверх состояния: живёт `seconds` и сама растворяется. */
  playEmotion(name, seconds = 2.4) {
    if (!EXPRESSIONS[name]) return;
    this.overlay = name;
    this.overlayLeft = seconds;
    if (name === 'happy') this.pulseDecal('blush', 0.35, seconds);
    if (name === 'surprised') this.pulseDecal('amazed', 0.5, Math.min(1.2, seconds));
    if (name === 'sad') this.pulseDecal('sweat', 0.4, seconds);
    if (name === 'angry') this.pulseDecal('veins', 0.5, seconds);
  }

  playGesture(name) {
    const gesture = GESTURES[name];
    if (!gesture) return;
    this.gesture = gesture;
    this.gestureTime = 0;
    if (gesture.clip) this.character.play(gesture.clip, 0.45);
  }

  pulseDecal(key, value, seconds) {
    const morph = DECALS[key];
    if (!morph || !this.character.hasMorph(morph)) return;
    const entry = this.decals.get(morph) || { value: 0, target: 0, left: 0 };
    entry.target = value;
    entry.left = seconds;
    this.decals.set(morph, entry);
  }

  /** Реакция на успешное действие или ошибку — заметная, но короткая. */
  react(kind) {
    if (kind === 'success') {
      this.playEmotion('happy', 2.6);
      this.pulseDecal('stars', 0.55, 1.1);
      this.playGesture('present');
    } else if (kind === 'error') {
      this.playEmotion('sad', 3.0);
      this.pulseDecal('sweat', 0.55, 2.4);
      this.playGesture('shrug');
    } else if (kind === 'greet') {
      this.playEmotion('happy', 3.0);
      this.playGesture('greet');
      this.pulseDecal('blush', 0.3, 2.5);
    } else if (kind === 'question') {
      this.playEmotion('doubt', 2.2);
      this.playGesture('tilt');
    }
  }

  setLevel(value) { this.level = clamp(value); }

  /** Веса гласных приходят из анализа звука; `open` — общая громкость рта. */
  setViseme(data) {
    this.visemeTarget.open = clamp(data.open ?? 0);
    this.visemeTarget.a = clamp(data.a ?? 0);
    this.visemeTarget.e = clamp(data.e ?? 0);
    this.visemeTarget.i = clamp(data.i ?? 0);
    this.visemeTarget.o = clamp(data.o ?? 0);
    this.visemeTarget.u = clamp(data.u ?? 0);
  }

  /** Курсор в нормали −1..1 — персонаж провожает его взглядом. */
  setPointer(x, y, active = true) {
    this.pointer.set(clamp(x, -1, 1), clamp(y, -1, 1));
    this.pointerActive = active;
  }

  // -------------------------------------------------------------- кадр

  update(delta, elapsed) {
    this.time = elapsed;
    this.character.clearMorphs();

    this._updateEnergy(delta);
    this._updateBlink(delta);
    this._updateGaze(delta);
    this._updateExpression(delta);
    this._updateLips(delta);
    this._updateDecals(delta);
    // жест раньше тела: он задаёт наклон головы, который тело в этом же кадре
    // и отрабатывает. В обратном порядке жест опаздывал на кадр
    this._updateGesture(delta);
    this._updateBody(delta);
  }

  _updateEnergy(delta) {
    // громкость сглаживается один раз здесь, дальше все ею пользуются
    this.levelSmooth = approach(this.levelSmooth, this.level, 7.0, delta);
    const target = this.params.energy * (0.85 + 0.35 * this.levelSmooth);
    this.energy = approach(this.energy, target, 2.0, delta);
  }

  // --- моргание -------------------------------------------------------

  _updateBlink(delta) {
    this.blinkTimer -= delta * (this.params.blink || 1);
    if (this.blinkTimer <= 0 && this.blinkPhase === 'idle') {
      this.blinkPhase = 'close';
      // изредка два быстрых моргания подряд — так делают люди, и это заметно
      this.blinkQueue = Math.random() < 0.18 ? 1 : 0;
      this.blinkTimer = randomBetween(2.2, 6.5);
    }

    if (this.blinkPhase === 'close') {
      this.blink += delta / 0.055;
      if (this.blink >= 1) { this.blink = 1; this.blinkPhase = 'open'; }
    } else if (this.blinkPhase === 'open') {
      this.blink -= delta / 0.11;
      if (this.blink <= 0) {
        this.blink = 0;
        if (this.blinkQueue > 0) { this.blinkQueue -= 1; this.blinkPhase = 'close'; }
        else this.blinkPhase = 'idle';
      }
    }
  }

  // --- взгляд ---------------------------------------------------------

  _updateGaze(delta) {
    this.gazeTimer -= delta;
    if (this.gazeTimer <= 0) {
      const toCamera = Math.random() < (this.params.gazeCamera ?? 0.5);
      if (toCamera) {
        this.gazeTarget.set(randomBetween(-0.1, 0.1), randomBetween(-0.06, 0.06));
        this.gazeTimer = randomBetween(1.4, 3.4);
      } else {
        // взгляд «в сторону мысли»: вверх и вбок, как при припоминании
        this.gazeTarget.set(randomBetween(-0.8, 0.8), randomBetween(-0.35, 0.6));
        this.gazeTimer = randomBetween(0.6, 1.8);
      }
    }

    if (this.pointerActive) {
      this.gazeTarget.x = lerp(this.gazeTarget.x, this.pointer.x, 0.75);
      this.gazeTarget.y = lerp(this.gazeTarget.y, -this.pointer.y, 0.75);
    }

    // микродрожание зрачка: без него взгляд выглядит стеклянным
    const jitterX = drift(this.time, 3.1, 2.6) * 0.02;
    const jitterY = drift(this.time, 7.7, 2.2) * 0.014;
    this.gaze.x = approach(this.gaze.x, clamp(this.gazeTarget.x + jitterX, -1, 1), 14, delta);
    this.gaze.y = approach(this.gaze.y, clamp(this.gazeTarget.y + jitterY, -1, 1), 14, delta);

    // хватает четырёх сторон: диагональные шейпы — их же сумма, и вместе с ними
    // зрачок уезжал бы вдвое дальше, чем нужно
    const set = (name, value) => { if (value > 0.001) this.character.addMorph(name, value); };
    const x = this.gaze.x;
    const y = this.gaze.y;
    set('look_L', clamp(-x));
    set('look_R', clamp(x));
    set('look_U', clamp(y));
    set('look_D', clamp(-y));

    // голова тянется за взглядом, но заметно слабее и с запаздыванием
    this.headTarget.yaw = -x * 0.28;
    this.headTarget.pitch = y * 0.16;
  }

  // --- мимика ---------------------------------------------------------

  _updateExpression(delta) {
    if (this.overlayLeft > 0) {
      this.overlayLeft -= delta;
      if (this.overlayLeft <= 0) this.overlay = null;
    }
    const active = this.overlay || this.expression;

    // все наборы плавно едут к нулю, активный — к своей силе
    for (const name of Object.keys(EXPRESSIONS)) {
      const preset = EXPRESSIONS[name];
      const target = name === active ? (preset.weight ?? 0) : 0;
      const current = approach(this.weights.get(name) ?? 0, target, 4.5, delta);
      this.weights.set(name, current);
      if (current < 0.004) continue;

      if (preset.brow) this.character.addMorph(preset.brow, current);
      if (preset.lid) {
        // при моргании форма век переходит из «открытой» в «закрытую» того же настроения
        this.character.addMorph(`${preset.lid}_OP`, current * (1 - this.blink));
        this.character.addMorph(`${preset.lid}_CLO`, current * this.blink);
      }
      if (preset.mouth) this.character.addMorph(`${preset.mouth}_OP`, current * (preset.mouthWeight ?? 0.4));
    }

    // обычное моргание поверх любой мимики
    this.character.addMorph('biyan', this.blink);

    // брови чуть живут сами: дыхание лица
    const micro = drift(this.time, 1.9, 0.6);
    this.character.addMorph('EB_UD_L', clamp(0.12 + micro * 0.1));
    this.character.addMorph('EB_UD_R', clamp(0.12 + micro * 0.1 + drift(this.time, 5.2, 0.5) * 0.03));
  }

  // --- губы -----------------------------------------------------------

  _updateLips(delta) {
    const speaking = this.state === 'speaking' && this.lipSync !== false;
    if (!speaking) {
      for (const key of Object.keys(this.visemeTarget)) this.visemeTarget[key] = 0;
    }
    // рот закрывается быстрее, чем открывается: иначе речь выглядит «жующей»
    for (const key of Object.keys(this.viseme)) {
      const target = this.visemeTarget[key];
      const rate = target > this.viseme[key] ? 26 : 16;
      this.viseme[key] = approach(this.viseme[key], target, rate, delta);
    }

    const open = this.viseme.open;
    if (open < 0.004 && !speaking) return;

    this.character.addMorph('jawOpen', open * 0.55);
    this.character.addMorph('jawOpen_a', this.viseme.a * open);
    this.character.addMorph('jawOpen_ei', this.viseme.e * open);
    this.character.addMorph('jawOpen_yi', this.viseme.i * open);
    this.character.addMorph('jawOpen_o', this.viseme.o * open);
    this.character.addMorph('jawOpen_wu', this.viseme.u * open);
    // губы округляются на «у» и «о» — форма читается даже издалека
    this.character.addMorph('mouthPucker', (this.viseme.u * 0.5 + this.viseme.o * 0.25) * open);
    this.character.addMorph('mouthFunnel', this.viseme.o * 0.3 * open);
  }

  _updateDecals(delta) {
    for (const [morph, entry] of this.decals) {
      entry.left -= delta;
      if (entry.left <= 0) entry.target = 0;
      entry.value = approach(entry.value, entry.target, 3.2, delta);
      if (entry.value < 0.002 && entry.target === 0) { this.decals.delete(morph); continue; }
      this.character.addMorph(morph, entry.value);
    }
  }

  // --- тело -----------------------------------------------------------

  _updateBody(delta) {
    const bones = this.character.bones;
    const speed = 0.62 * this.energy;
    // вдох длиннее выдоха — ровный синус выдал бы механику
    const phase = (this.time * speed) % 1;
    const curve = phase < 0.42
      ? Math.sin((phase / 0.42) * Math.PI * 0.5)
      : Math.cos(((phase - 0.42) / 0.58) * Math.PI * 0.5);
    this.breath = approach(this.breath, curve, 8, delta);

    this.lean = approach(this.lean, this.params.lean ?? 0, 2.2, delta);

    // «дыхание и микродвижения» можно выключить в меню — остаётся только взгляд
    const life = this.idleMotion ? 1 : 0;
    this.sway = drift(this.time, 2.4, 0.35) * 0.02 * this.energy * life;

    const idleYaw = drift(this.time, 11.3, 0.42) * 0.05 * life;
    const idlePitch = drift(this.time, 4.6, 0.38) * 0.03 * life;
    const idleRoll = drift(this.time, 8.1, 0.31) * 0.04 * life;

    this.head.yaw = approach(this.head.yaw, this.headTarget.yaw + idleYaw, 5, delta);
    this.head.pitch = approach(
      this.head.pitch, this.headTarget.pitch + this.gestureHead.pitch + idlePitch, 5, delta);
    this.head.roll = approach(
      this.head.roll, this.headTarget.roll + this.gestureHead.roll + idleRoll, 5, delta);

    // Речь чуть подчёркивается кивком, но по сглаженной громкости и слабее:
    // на сырой она дёргала голову в такт каждому блоку звука. И добавляется
    // через ту же сглаженную величину, а не поверх готового угла.
    const accent = this.state === 'speaking' ? this.levelSmooth * 0.016 : 0;

    const breath = this.breath * life;
    this._rotate(bones.spine, [breath * 0.012 + this.lean * 0.5, this.sway * 0.4, 0]);
    this._rotate(bones.spine1, [breath * 0.020 + this.lean * 0.3, this.sway * 0.3, this.sway * 0.5]);
    this._rotate(bones.spine2, [breath * 0.024, this.sway * 0.2, -this.sway * 0.4]);
    this._rotate(bones.neck, [this.head.pitch * 0.35 - accent, this.head.yaw * 0.35, this.head.roll * 0.35]);
    this._rotate(bones.head, [this.head.pitch * 0.65 - accent * 0.6, this.head.yaw * 0.65, this.head.roll * 0.65]);

    // глазные яблоки не крутим костями: направление зрачка задают шейпы look_*,
    // они нарисованы художником и не расходятся с формой века

    // плечи поднимаются на вдохе — заметно только краем глаза, но работает
    this._rotate(bones.clavicleL, [0, 0, breath * 0.014]);
    this._rotate(bones.clavicleR, [0, 0, -breath * 0.014]);
  }

  _updateGesture(delta) {
    const target = this.gesture ? 1 : 0;
    if (this.gesture) {
      this.gestureTime += delta;
      if (this.gestureTime >= this.gesture.duration) this.gesture = null;
    }
    this.gestureWeight = approach(this.gestureWeight, target, 4.0, delta);
    // вклад в голову пересчитывается с нуля каждый кадр. Раньше он писался
    // прямо в headTarget и после наклона головы там навсегда оставался угол —
    // персонаж так и стоял со склонённой головой до перезапуска
    this.gestureHead.pitch = 0;
    this.gestureHead.roll = 0;
    if (this.gestureWeight < 0.004 || !this.gesture) return;

    const gesture = this.gesture;
    // мягкий вход и выход внутри самого жеста, чтобы он не «щёлкал»
    const progress = clamp(this.gestureTime / gesture.duration);
    const envelope = Math.sin(progress * Math.PI) ** 0.6;
    const weight = this.gestureWeight * envelope;

    if (gesture.pose) {
      for (const [key, angles] of Object.entries(gesture.pose)) {
        this._rotate(this.character.bones[key], angles.map((value) => value * weight));
      }
    }
    if (gesture.wave) {
      const bone = this.character.bones[gesture.wave.bone];
      const angles = [0, 0, 0];
      angles[gesture.wave.axis] = Math.sin(this.gestureTime * gesture.wave.speed) * gesture.wave.amount * weight;
      this._rotate(bone, angles);
    }
    if (gesture.head) {
      const { pitch = 0, roll = 0, cycles = 0 } = gesture.head;
      const beat = cycles ? Math.sin(progress * Math.PI * 2 * cycles) : 1;
      this.gestureHead.pitch = pitch * beat * weight;
      this.gestureHead.roll = roll * weight;
    }
  }

  /** Добавляет поворот к текущей (уже проигранной анимацией) позе кости. */
  _rotate(bone, angles) {
    if (!bone) return;
    for (let axis = 0; axis < 3; axis += 1) {
      const angle = angles[axis];
      if (!angle) continue;
      this._temp.setFromAxisAngle(AXES[axis], angle);
      bone.quaternion.multiply(this._temp);
    }
  }
}

export { EXPRESSIONS, GESTURES };
