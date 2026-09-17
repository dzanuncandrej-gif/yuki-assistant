/**
 * Персонаж: загрузка модели, материалы, карта костей и мимических морфов.
 *
 * Модель приходит из `scripts/build_avatar.py`: один скиннед-меш из
 * одиннадцати кусков, 274 кости и 148 блендшейпов с именами. Здесь она
 * приводится к удобному виду — материалы собираются заново под аниме-подачу,
 * кости и морфы раскладываются по понятным именам, чтобы «мозг» персонажа
 * (behaviour.js) не знал ничего про внутренности glTF.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const HEIGHT = 1.7;          // метры: под этот рост настроены камера и свет
const TOON_STEPS = 4;        // ступеней в градиенте сел-шейдинга
const SOURCE_FPS = 30;       // экспорт запечён на 30 кадрах в секунду

/**
 * В модели одна запечённая анимация — «показ персонажа» на 13 секунд. Целиком
 * она не годится: в середине девушка отворачивается и позирует. Зато внутри
 * есть три пригодных куска, и мы режем их на отдельные клипы.
 *
 * Границы найдены покадровым просмотром исходника, время — в секундах.
 */
const SEGMENTS = {
  idle: { from: 10.5, to: 13.2, loop: THREE.LoopPingPong, speed: 0.6 },
  flourish: { from: 6.0, to: 10.0, loop: THREE.LoopOnce, speed: 0.95 },
  aside: { from: 2.4, to: 6.0, loop: THREE.LoopOnce, speed: 0.85 },
};

/** Ступенчатый градиент для MeshToonMaterial — мягкая, но читаемая светотень. */
function toonGradient(steps) {
  const data = new Uint8Array(steps * 4);
  for (let i = 0; i < steps; i += 1) {
    // нижняя ступень не уходит в чёрный: в тени лицо должно остаться живым
    const value = Math.round(255 * (0.42 + 0.58 * (i / (steps - 1)) ** 0.85));
    data.set([value, value, value, 255], i * 4);
  }
  const texture = new THREE.DataTexture(data, steps, 1, THREE.RGBAFormat);
  texture.minFilter = THREE.NearestFilter;
  texture.magFilter = THREE.NearestFilter;
  texture.needsUpdate = true;
  return texture;
}

/** Пришивает к материалу ободок света по контуру — фигура отделяется от фона. */
function addRimLight(material, color, strength) {
  material.userData.rim = { color: new THREE.Color(color), strength };
  material.onBeforeCompile = (shader) => {
    shader.uniforms.rimColor = { value: material.userData.rim.color };
    shader.uniforms.rimStrength = { value: material.userData.rim.strength };
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>
         uniform vec3 rimColor;
         uniform float rimStrength;`,
      )
      .replace(
        '#include <dithering_fragment>',
        `#include <dithering_fragment>
         float rim = 1.0 - clamp(dot(normalize(vNormal), normalize(vViewPosition)), 0.0, 1.0);
         gl_FragColor.rgb += rimColor * pow(rim, 3.0) * rimStrength;`,
      );
    material.userData.shader = shader;
  };
}

/** Имена костей лица и корпуса, на которые опирается вся процедурная анимация. */
const BONES = {
  root: 'Bip001',
  pelvis: 'Bip001-Pelvis',
  spine: 'Bip001-Spine',
  spine1: 'Bip001-Spine1',
  spine2: 'Bip001-Spine2',
  neck: 'Bip001-Neck',
  head: 'Bip001-Head',
  headTip: 'Bone_head',
  jaw: 'mouth',
  eyeL: 'Bon_eyeball_L',
  eyeR: 'Bon_eyeball_R',
  clavicleL: 'Bip001-L-Clavicle',
  clavicleR: 'Bip001-R-Clavicle',
  armL: 'Bip001-L-UpperArm',
  armR: 'Bip001-R-UpperArm',
  foreL: 'Bip001-L-Forearm',
  foreR: 'Bip001-R-Forearm',
  handL: 'Bip001-L-Hand',
  handR: 'Bip001-R-Hand',
  browL: 'Bon_eyebrow02_L',
  browR: 'Bon_eyebrow02_R',
  chestL: 'Bn_l_xiong_001',
  chestR: 'Bn_r_xiong_001',
};

export class Character {
  constructor(manifest, basePath) {
    this.manifest = manifest;
    this.basePath = basePath;
    this.root = new THREE.Group();
    this.bones = {};
    this.rest = new Map();      // исходные повороты костей: процедурика идёт поверх
    this.morphIndex = new Map();
    this.meshes = [];
    this.mixer = null;
    this.idleAction = null;
    this.height = HEIGHT;
    this._influences = null;
  }

  async load(onProgress) {
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(`${this.basePath}/${this.manifest.model}`, (event) => {
      if (onProgress && event.total) onProgress(event.loaded / event.total);
    });

    const model = gltf.scene;
    this.root.add(model);
    await this._applyMaterials(model);
    this._collectRig(model);
    this._normalize(model);

    if (gltf.animations.length) this._buildClips(model, gltf.animations[0]);
    return this;
  }

  // ------------------------------------------------------------- анимации

  _buildClips(model, source) {
    this.mixer = new THREE.AnimationMixer(model);
    this.actions = {};

    // какие кости трогает запечённый клип. Остальные микшер не переписывает, и
    // процедурная добавка к ним копилась бы кадр за кадром — глаза от этого
    // начинали вращаться без остановки
    this.animated = new Set();
    for (const track of source.tracks) {
      const dot = track.name.lastIndexOf('.');
      this.animated.add(dot < 0 ? track.name : track.name.slice(0, dot));
    }
    for (const [name, segment] of Object.entries(SEGMENTS)) {
      const clip = THREE.AnimationUtils.subclip(
        source, name,
        Math.round(segment.from * SOURCE_FPS),
        Math.round(segment.to * SOURCE_FPS),
        SOURCE_FPS,
      );
      const action = this.mixer.clipAction(clip);
      action.setLoop(segment.loop, segment.loop === THREE.LoopOnce ? 1 : Infinity);
      action.clampWhenFinished = segment.loop === THREE.LoopOnce;
      action.timeScale = segment.speed;
      this.actions[name] = action;
    }
    this.current = 'idle';
    this.actions.idle.play();

    // одноразовый клип сам возвращает управление спокойной стойке
    this.mixer.addEventListener('finished', (event) => {
      if (event.action !== this.actions[this.current]) return;
      this.play('idle', 0.5);
    });
  }

  /** Переключает клип с перекрёстным затуханием — стыков не видно. */
  play(name, fade = 0.35) {
    if (!this.actions || !this.actions[name] || this.current === name) return;
    const next = this.actions[name];
    const previous = this.actions[this.current];
    next.reset();
    next.setEffectiveWeight(1);
    next.play();
    if (previous) previous.crossFadeTo(next, fade, false);
    this.current = name;
  }

  // ------------------------------------------------------------- материалы

  async _applyMaterials(model) {
    const textures = new Map();
    const loader = new THREE.TextureLoader();
    const gradient = toonGradient(TOON_STEPS);

    const load = async (file) => {
      if (!textures.has(file)) {
        const texture = await loader.loadAsync(`${this.basePath}/textures/${file}`);
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.flipY = false;              // glTF хранит UV с началом сверху
        texture.anisotropy = 8;
        textures.set(file, texture);
      }
      return textures.get(file);
    };

    const hidden = new Set(this.manifest.hidden || []);
    const jobs = [];
    model.traverse((node) => {
      if (!node.isMesh && !node.isSkinnedMesh) return;
      const source = node.material;
      const name = source.name || '';
      if (hidden.has(name)) { node.visible = false; return; }

      node.frustumCulled = false;           // морфы и кости выводят вершины за исходный бокс
      node.castShadow = false;
      node.receiveShadow = false;
      this.meshes.push(node);

      const file = (this.manifest.textures || {})[name];
      const isEye = name.includes('_eye') || name.includes('gaoguang');
      const isLash = name.includes('eyelash');

      // глаза и блики светятся сами: в аниме они не должны попадать в тень
      const material = isEye
        ? new THREE.MeshBasicMaterial({ toneMapped: false })
        : new THREE.MeshToonMaterial({ gradientMap: gradient });

      material.name = name;
      material.side = THREE.DoubleSide;
      material.transparent = source.transparent || isLash;
      material.alphaTest = material.transparent ? 0.02 : 0;
      material.depthWrite = !isLash;
      material.skinning = true;
      if (!isEye) addRimLight(material, isLash ? 0x8fb8ff : 0xa8ccff, isLash ? 0.06 : 0.16);

      node.material = material;
      if (file) jobs.push(load(file).then((texture) => { material.map = texture; material.needsUpdate = true; }));
    });
    await Promise.all(jobs);
  }

  // ------------------------------------------------------------- риг

  _collectRig(model) {
    const byName = new Map();
    model.traverse((node) => { if (node.isBone) byName.set(node.name, node); });

    // glTF-имена могли слегка измениться при загрузке — ищем и по «очищенному» виду
    const relaxed = new Map();
    byName.forEach((bone, name) => relaxed.set(name.replace(/[^a-z0-9]/gi, '').toLowerCase(), bone));

    for (const [key, name] of Object.entries(BONES)) {
      const bone = byName.get(name) || relaxed.get(name.replace(/[^a-z0-9]/gi, '').toLowerCase());
      if (bone) {
        this.bones[key] = bone;
        this.rest.set(bone, { quaternion: bone.quaternion.clone(), position: bone.position.clone() });
      }
    }

    const first = this.meshes.find((mesh) => mesh.morphTargetDictionary);
    if (first) {
      Object.entries(first.morphTargetDictionary).forEach(([name, index]) => {
        this.morphIndex.set(name, index);
      });
      this._influences = this.meshes
        .filter((mesh) => mesh.morphTargetInfluences)
        .map((mesh) => mesh.morphTargetInfluences);
    }
  }

  /** Ставит модель ногами в ноль и приводит рост к метрам сцены. */
  _normalize(model) {
    model.updateWorldMatrix(true, true);
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const scale = HEIGHT / Math.max(size.y, 1e-6);
    model.scale.multiplyScalar(scale);

    model.updateWorldMatrix(true, true);
    const scaled = new THREE.Box3().setFromObject(model);
    const centre = scaled.getCenter(new THREE.Vector3());
    model.position.x -= centre.x;
    model.position.z -= centre.z;
    model.position.y -= scaled.min.y;

    this.headHeight = this.bones.head
      ? this.bones.head.getWorldPosition(new THREE.Vector3()).y
      : HEIGHT * 0.88;
  }

  // ------------------------------------------------------------- морфы

  hasMorph(name) { return this.morphIndex.has(name); }

  /** Ставит вес блендшейпа сразу на все куски меша — они делят один набор целей. */
  setMorph(name, value) {
    const index = this.morphIndex.get(name);
    if (index === undefined || !this._influences) return;
    const clamped = value < 0 ? 0 : (value > 1 ? 1 : value);
    for (const influences of this._influences) influences[index] = clamped;
  }

  addMorph(name, value) {
    const index = this.morphIndex.get(name);
    if (index === undefined || !this._influences) return;
    for (const influences of this._influences) {
      const next = influences[index] + value;
      influences[index] = next < 0 ? 0 : (next > 1 ? 1 : next);
    }
  }

  clearMorphs() {
    if (!this._influences) return;
    for (const influences of this._influences) influences.fill(0);
  }

  morphNames() { return [...this.morphIndex.keys()]; }

  // ------------------------------------------------------------- кости

  restOf(bone) { return this.rest.get(bone); }

  /**
   * Готовит скелет к процедурной добавке.
   *
   * Кости, которые ведёт клип, микшер уже переписал — их можно домножать.
   * Кости вне клипа надо вернуть в исходное положение вручную, иначе добавка
   * накапливается и поза уезжает в бесконечность.
   */
  beginPose() {
    if (!this.animated) return;
    for (const bone of Object.values(this.bones)) {
      if (this.animated.has(bone.name)) continue;
      const rest = this.rest.get(bone);
      if (rest) bone.quaternion.copy(rest.quaternion);
    }
  }

  update(delta) {
    if (this.mixer) this.mixer.update(delta);
    this.beginPose();
  }

  /** Освобождает видеопамять при смене персонажа. */
  dispose() {
    if (this.mixer) this.mixer.stopAllAction();
    const textures = new Set();
    this.root.traverse((node) => {
      if (!node.isMesh && !node.isSkinnedMesh) return;
      node.geometry.dispose();
      const material = node.material;
      if (material.map) textures.add(material.map);
      if (material.gradientMap) textures.add(material.gradientMap);
      material.dispose();
    });
    textures.forEach((texture) => texture.dispose());
  }
}
