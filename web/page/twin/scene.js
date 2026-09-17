/**
 * Предприятие как живой организм.
 *
 * Сцена не иллюстрирует числа, а показывает их напрямую: высота светового
 * клинка над участком — его загрузка, стопка перед участком — очередь, поток
 * искр между участками — заказы. Ничего декоративного, за чем не стоит
 * величина, здесь нет: деталь без числа обесценивает соседнюю деталь с числом,
 * потому что зритель перестаёт отличать данные от оформления.
 *
 * Главное решение — сдержанность цвета. Спокойный участок здесь почти не
 * светится: холодная сталь, различимая, но не яркая. Горит только то, где
 * действительно беда. Раскрашенная в три ядовитых цвета сцена читается как
 * игра, а не как цех, и, что хуже, в ней негде поставить настоящий акцент —
 * когда светится всё, не выделено ничто.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

// Сталь — норма, янтарь — напряжение, кровь — предел. Зелёного нет вовсе:
// «хорошо» здесь означает «не привлекает внимания», а не «горит зелёным».
const STEEL = new THREE.Color(0x8fa6c8);
const WARN = new THREE.Color(0xd9a047);
const CRIT = new THREE.Color(0xe0423c);
const CRIMSON = 0xb8332e;

// Проводник стоит ближе к зрителю, чем линия: так он читается фигурой, а не
// точкой у горизонта. Крупная константа рядом с камерой — самый дешёвый способ
// задать масштаб всей сцене.
const GUIDE = { x: -11.0, z: 5.5, height: 4.8 };

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ease = (t) => t * t * (3 - 2 * t);
const easeOut = (t) => 1 - Math.pow(1 - t, 3);

/** Цвет по загрузке. Ниже порога — ровная сталь, выше — разогрев до предела. */
function tone(load) {
  const colour = new THREE.Color();
  if (load < 0.8) return colour.copy(STEEL);
  if (load < 0.93) return colour.copy(STEEL).lerp(WARN, (load - 0.8) / 0.13);
  return colour.copy(WARN).lerp(CRIT, clamp((load - 0.93) / 0.07, 0, 1));
}

/** Вертикальный градиент для светового клинка: ярко у основания, в ничто вверху. */
function bladeTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 8; canvas.height = 128;
  const paint = canvas.getContext('2d');
  const grad = paint.createLinearGradient(0, 128, 0, 0);
  grad.addColorStop(0.0, 'rgba(255,255,255,0.95)');
  grad.addColorStop(0.25, 'rgba(255,255,255,0.42)');
  grad.addColorStop(0.7, 'rgba(255,255,255,0.12)');
  grad.addColorStop(1.0, 'rgba(255,255,255,0)');
  paint.fillStyle = grad;
  paint.fillRect(0, 0, 8, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

let BLADE = null;


class Node {
  constructor(data, parent) {
    this.data = data;
    this.load = 0;
    this.queue = 0;
    this.want = { load: data.load, queue: data.queue };
    this.dim = 1;
    this.group = new THREE.Group();
    this.group.position.set(...data.position);
    parent.add(this.group);
    this._build();
  }

  _build() {
    // Площадка: тёмный полированный диск. Он ничего не сообщает и не должен —
    // его дело давать опору и ловить отражение, чтобы участок стоял на полу,
    // а не висел над ним.
    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(1.0, 1.08, 0.09, 64),
      new THREE.MeshStandardMaterial({ color: 0x0c1119, roughness: 0.28, metalness: 0.9 }),
    );
    pad.position.y = 0.045;
    this.group.add(pad);

    this.ring = new THREE.Mesh(
      new THREE.TorusGeometry(1.04, 0.012, 8, 96),
      new THREE.MeshBasicMaterial({ color: 0x8fa6c8, transparent: true, opacity: 0.5 }),
    );
    this.ring.rotation.x = Math.PI / 2;
    this.ring.position.y = 0.095;
    this.group.add(this.ring);

    // Световой клинок — это и есть загрузка. Плоскость с градиентом на
    // сложении вместо светящегося цилиндра: цилиндр читается как пластиковая
    // трубка, а градиент на сложении — как свет, которого не касаются.
    if (!BLADE) BLADE = bladeTexture();
    this.blade = new THREE.Mesh(
      new THREE.PlaneGeometry(0.62, 1),
      new THREE.MeshBasicMaterial({
        map: BLADE, color: 0x8fa6c8, transparent: true, opacity: 0.55,
        blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
      }),
    );
    this.group.add(this.blade);

    this.core = new THREE.Mesh(
      new THREE.CylinderGeometry(0.035, 0.05, 1, 8, 1, true),
      new THREE.MeshBasicMaterial({ color: 0xdce7f7, transparent: true, opacity: 0.7,
                                    blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    this.group.add(this.core);

    this.glow = new THREE.PointLight(0x8fa6c8, 0, 8, 2);
    this.glow.position.y = 0.9;
    this.group.add(this.glow);

    // Очередь — стопка тонких пластин, а не куча кубиков. Кубики выглядят
    // игрушечными блоками; пластины читаются как накопившиеся заказы.
    this.pile = new THREE.InstancedMesh(
      new THREE.BoxGeometry(0.34, 0.022, 0.44),
      new THREE.MeshStandardMaterial({ color: 0x1b2434, roughness: 0.55, metalness: 0.5,
                                       emissive: 0x000000, emissiveIntensity: 1 }),
      Node.PILE_MAX,
    );
    this.pile.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.pile.count = 0;
    this.pile.position.set(-1.32, 0.03, 0);
    this.group.add(this.pile);

    this.pile.userData.slots = [];
    for (let i = 0; i < Node.PILE_MAX; i++) {
      const column = Math.floor(i / 14);
      const level = i % 14;
      this.pile.userData.slots.push({
        x: -column * 0.42,
        y: level * 0.028,
        z: (Math.random() - 0.5) * 0.06,
        // Лёгкий разброс поворота: идеально ровная стопка выглядит нарисованной.
        turn: (Math.random() - 0.5) * 0.14,
      });
    }
    this._pose = new THREE.Object3D();

    this.hit = new THREE.Mesh(
      new THREE.CylinderGeometry(1.25, 1.25, 2.6, 12),
      new THREE.MeshBasicMaterial({ visible: false }),
    );
    this.hit.position.y = 1.1;
    this.hit.userData.station = this.data.id;
    this.group.add(this.hit);
  }

  set(data) {
    this.data = data;
    this.want.load = data.load;
    this.want.queue = data.queue;
  }

  step(dt, time, focused, camera) {
    this.load += (this.want.load - this.load) * clamp(dt * 3.0, 0, 1);
    this.queue += (this.want.queue - this.queue) * clamp(dt * 2.2, 0, 1);
    const target = focused === null ? 1 : (focused === this.data.id ? 1 : 0.3);
    this.dim += (target - this.dim) * clamp(dt * 3.2, 0, 1);

    const colour = tone(this.load);
    const heat = clamp((this.load - 0.9) / 0.1, 0, 1);
    const over = clamp((this.load - 0.98) * 30, 0, 1);
    // Пульс включается только на перегрузе, и это не украшение: ровно горящий
    // столб на девяноста девяти и на ста трёх процентах выглядит одинаково, а
    // разница между ними — растёт очередь или нет.
    const beat = over > 0 ? 0.78 + 0.22 * Math.sin(time * 6.5) : 1;

    const height = clamp(this.load, 0.06, 1.05) * 3.6;
    this.blade.scale.set(1, height, 1);
    this.blade.position.y = height / 2;
    this.blade.material.color.copy(colour);
    this.blade.material.opacity = (0.3 + heat * 0.5) * beat * this.dim;
    // Клинок разворачивается к камере: плоскость, увиденная с ребра, исчезает.
    this.blade.quaternion.copy(camera.quaternion);

    this.core.scale.set(1, height, 1);
    this.core.position.y = height / 2;
    this.core.material.color.copy(colour).lerp(new THREE.Color(0xffffff), 0.45 - heat * 0.35);
    this.core.material.opacity = (0.34 + heat * 0.5) * beat * this.dim;

    this.ring.material.color.copy(colour);
    this.ring.material.opacity = (0.32 + heat * 0.55) * beat * this.dim;

    this.glow.color.copy(colour);
    this.glow.intensity = (0.5 + heat * 3.2 + over * 3.0) * beat * this.dim;

    // Шкала стопки логарифмическая: очередь бывает и три заказа, и четыреста, а
    // линейная при таком размахе показывает либо пустоту, либо стену.
    const shown = Math.round(clamp(Math.log10(1 + this.queue) * 16, 0, Node.PILE_MAX));
    if (shown !== this.pile.count) {
      this.pile.count = shown;
      for (let i = 0; i < shown; i++) {
        const slot = this.pile.userData.slots[i];
        this._pose.position.set(slot.x, slot.y, slot.z);
        this._pose.rotation.set(0, slot.turn, 0);
        this._pose.updateMatrix();
        this.pile.setMatrixAt(i, this._pose.matrix);
      }
      this.pile.instanceMatrix.needsUpdate = true;
    }
    this.pile.material.emissive.copy(colour);
    this.pile.material.emissiveIntensity = heat * 0.5 * this.dim;
  }
}
Node.PILE_MAX = 42;


class Flow {
  constructor(from, to, parent, options = {}) {
    this.rework = !!options.rework;
    const lift = this.rework ? 2.4 : 0.42;
    const middle = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5);
    middle.y += lift;
    if (this.rework) middle.z -= 2.6;

    this.curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(from.x, 0.36, from.z),
      middle,
      new THREE.Vector3(to.x, 0.36, to.z),
    ]);

    // Направляющая нить тонкая почти до предела видимости: она нужна, чтобы
    // глаз достроил путь между искрами, и не нужна ни для чего больше.
    this.line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(this.curve.getPoints(48)),
      new THREE.LineBasicMaterial({
        color: this.rework ? 0x8c3b3b : 0x2c3a52, transparent: true,
        opacity: this.rework ? 0.34 : 0.42,
      }),
    );
    parent.add(this.line);

    const count = this.rework ? 12 : 26;
    this.spots = new Float32Array(count * 3);
    this.at = new Float32Array(count);
    for (let i = 0; i < count; i++) this.at[i] = i / count;

    const shape = new THREE.BufferGeometry();
    shape.setAttribute('position', new THREE.BufferAttribute(this.spots, 3));
    this.dots = new THREE.Points(shape, new THREE.PointsMaterial({
      color: this.rework ? 0xd06a63 : 0xcfe0f5,
      size: this.rework ? 0.055 : 0.072,
      transparent: true, opacity: 0.9, depthWrite: false,
      blending: THREE.AdditiveBlending, sizeAttenuation: true,
    }));
    parent.add(this.dots);
    this.speed = 0.16;
    this.point = new THREE.Vector3();
  }

  step(dt, speed, dim) {
    this.speed += (speed - this.speed) * clamp(dt * 2, 0, 1);
    for (let i = 0; i < this.at.length; i++) {
      this.at[i] = (this.at[i] + this.speed * dt) % 1;
      this.curve.getPointAt(this.at[i], this.point);
      this.spots[i * 3] = this.point.x;
      this.spots[i * 3 + 1] = this.point.y;
      this.spots[i * 3 + 2] = this.point.z;
    }
    this.dots.geometry.attributes.position.needsUpdate = true;
    this.dots.material.opacity = 0.3 + 0.6 * dim;
    this.line.material.opacity = (this.rework ? 0.12 : 0.16) + 0.26 * dim;
  }
}


export class Factory {
  constructor(canvas, labels) {
    this.canvas = canvas;
    this.labels = labels;
    this.nodes = new Map();
    this.flows = [];
    this.focused = null;
    this.state = 'idle';
    this.level = 0;
    // Свой отсчёт времени вместо THREE.Clock: он объявлен устаревшим и пишет об
    // этом в консоль при каждой загрузке. Консоль с предупреждениями на показе
    // клиенту стоит дороже, чем четыре строки собственного таймера.
    this._last = performance.now() / 1000;
    this._time = 0;
    this.shot = null;
    this._picked = () => {};
    this._build();
  }

  _build() {
    const renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    this.renderer = renderer;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x04060a);
    // Туман отодвинут далеко. Раньше он начинался на шестнадцати единицах и
    // съедал проводника вместе с дальним краем линии: фигура выцветала до
    // фона ровно там, где на неё и надо смотреть.
    this.scene.fog = new THREE.Fog(0x04060a, 34, 96);

    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 260);
    this.camera.position.set(-8.5, 3.0, 12.0);
    this.look = new THREE.Vector3(GUIDE.x, 2.3, GUIDE.z);
    this.camera.lookAt(this.look);

    this._environment();
    this._lights();
    this._ground();

    this.root = new THREE.Group();
    this.scene.add(this.root);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(this.scene, this.camera));
    // Слабое свечение с высоким порогом. Сильное свечение с низким порогом
    // размывает всё подряд в мыло и есть первый признак самодельной сцены:
    // светиться должно то, что горячее, а не то, что просто светлое.
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.52, 0.72, 0.34);
    composer.addPass(this.bloom);
    composer.addPass(new OutputPass());
    this.composer = composer;

    this.ray = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.canvas.addEventListener('pointerdown', (event) => this._pick(event));

    this._resize();
    window.addEventListener('resize', () => this._resize());
    renderer.setAnimationLoop(() => this._frame());
  }

  /**
   * Карта окружения из простого градиента.
   *
   * Без неё физический материал нечего отражать, и доспех, металл площадок и
   * полированный пол выглядят плоской заливкой — сцена мгновенно читается как
   * набор раскрашенных фигур. Полноценная панорама здесь не нужна: отражения
   * мелкие, а вес и время загрузки заметные.
   */
  _environment() {
    const canvas = document.createElement('canvas');
    canvas.width = 4; canvas.height = 128;
    const paint = canvas.getContext('2d');
    const grad = paint.createLinearGradient(0, 0, 0, 128);
    grad.addColorStop(0.00, '#3a4a6b');
    grad.addColorStop(0.40, '#131a28');
    grad.addColorStop(0.58, '#2a1a16');
    grad.addColorStop(1.00, '#05070c');
    paint.fillStyle = grad; paint.fillRect(0, 0, 4, 128);
    const texture = new THREE.CanvasTexture(canvas);
    texture.mapping = THREE.EquirectangularReflectionMapping;
    texture.colorSpace = THREE.SRGBColorSpace;
    this.scene.environment = texture;
  }

  /** Свет ставится как в студии: ключевой, контровой и слабая заливка. */
  _lights() {
    this.scene.add(new THREE.HemisphereLight(0x35496e, 0x04060a, 0.32));

    const key = new THREE.DirectionalLight(0xfff1dd, 1.5);
    key.position.set(9, 15, 12);
    this.scene.add(key);

    const rim = new THREE.DirectionalLight(0x86aaff, 1.9);
    rim.position.set(-12, 9, -14);
    this.scene.add(rim);

    const fill = new THREE.DirectionalLight(0xbfd2f0, 0.35);
    fill.position.set(-4, 3, 14);
    this.scene.add(fill);
  }

  _ground() {
    // Сетка-миллиметровка убрана. Она мгновенно превращает любую сцену в
    // техническое демо; вместо неё — полированный пол и несколько длинных
    // линий вдоль оси потока, читающихся как разметка цеха.
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(160, 160),
      new THREE.MeshStandardMaterial({ color: 0x070a11, roughness: 0.2, metalness: 0.95 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.03;
    this.scene.add(floor);

    const lane = new THREE.Group();
    for (const z of [-4.6, -3.0, 3.0, 4.6]) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(-26, 0.005, z), new THREE.Vector3(24, 0.005, z),
        ]),
        new THREE.LineBasicMaterial({ color: 0x1a2434, transparent: true,
                                      opacity: Math.abs(z) > 4 ? 0.3 : 0.5 }),
      );
      lane.add(line);
    }
    this.scene.add(lane);
  }

  async build(state, samuraiUrl) {
    for (const data of state.stations) {
      this.nodes.set(data.id, new Node(data, this.root));
      const tag = document.createElement('div');
      tag.className = 'tag';
      tag.innerHTML = `<b></b><i></i><u data-load>—</u>`;
      tag.querySelector('b').textContent = data.name;
      tag.querySelector('i').textContent = data.role;
      tag.addEventListener('click', () => this._picked(data.id));
      this.labels.appendChild(tag);
      this.nodes.get(data.id).tag = tag;
    }

    const spot = (id) => new THREE.Vector3(...this.nodes.get(id).data.position);
    for (let i = 0; i < state.stations.length - 1; i++) {
      const a = state.stations[i], b = state.stations[i + 1];
      this.flows.push(Object.assign(new Flow(spot(a.id), spot(b.id), this.root), { from: a.id }));
    }
    for (const data of state.stations) {
      if (data.rework_to) {
        this.flows.push(Object.assign(
          new Flow(spot(data.id), spot(data.rework_to), this.root, { rework: true }),
          { from: data.id },
        ));
      }
    }

    if (samuraiUrl) await this._guide(samuraiUrl);
    this.update(state);
    return this;
  }

  /**
   * Проводник.
   *
   * У него собственный свет — три источника вплотную, — и это не щедрость, а
   * необходимость: общего света сцены на фигуру не хватает, она уходит в
   * силуэт и теряется. Показывать зрителю персонажа, которого он вынужден
   * искать глазами, — то же самое, что не показывать вовсе.
   */
  async _guide(url) {
    const dais = new THREE.Mesh(
      new THREE.CylinderGeometry(1.9, 2.15, 0.26, 64),
      new THREE.MeshStandardMaterial({ color: 0x0b1018, roughness: 0.22, metalness: 0.95 }),
    );
    dais.position.set(GUIDE.x, 0.13, GUIDE.z);
    this.root.add(dais);

    const edge = new THREE.Mesh(
      new THREE.TorusGeometry(1.94, 0.016, 8, 96),
      new THREE.MeshBasicMaterial({ color: CRIMSON, transparent: true, opacity: 0.75 }),
    );
    edge.rotation.x = Math.PI / 2;
    edge.position.set(GUIDE.x, 0.27, GUIDE.z);
    this.root.add(edge);
    this.daisEdge = edge;

    const key = new THREE.SpotLight(0xfff0d8, 46, 18, Math.PI / 5.5, 0.55, 1.6);
    key.position.set(GUIDE.x + 3.4, 7.2, GUIDE.z + 4.0);
    key.target.position.set(GUIDE.x, 1.9, GUIDE.z);
    this.root.add(key, key.target);

    const rim = new THREE.PointLight(0x9ec2ff, 14, 13, 2);
    rim.position.set(GUIDE.x - 3.2, 3.6, GUIDE.z - 3.0);
    this.root.add(rim);

    this.aura = new THREE.PointLight(CRIMSON, 2.0, 11, 2);
    this.aura.position.set(GUIDE.x, 2.2, GUIDE.z + 1.4);
    this.root.add(this.aura);

    try {
      const gltf = await new GLTFLoader().loadAsync(url);
      const model = gltf.scene;
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const centre = box.getCenter(new THREE.Vector3());
      const scale = GUIDE.height / Math.max(size.y, 0.001);
      model.scale.setScalar(scale);
      model.position.set(
        GUIDE.x - centre.x * scale,
        0.26 - box.min.y * scale,
        GUIDE.z - centre.z * scale,
      );
      // Три четверти оборота: анфас статичен, профиль обезличивает. Развёрнутый
      // к линии и вполоборота к зрителю, он читается как хозяин, показывающий цех.
      model.rotation.y = Math.PI * 0.30;
      model.traverse((node) => {
        if (!node.isMesh || !node.material) return;
        const material = node.material;
        material.envMapIntensity = 2.2;
        if (material.metalness !== undefined) material.metalness = Math.min(1, (material.metalness ?? 0) + 0.25);
        if (material.roughness !== undefined) material.roughness = Math.max(0.09, (material.roughness ?? 1) * 0.75);
        if (material.map) material.map.anisotropy = 8;
      });
      this.root.add(model);
      this.guide = model;
      if (gltf.animations?.length) {
        this.mixer = new THREE.AnimationMixer(model);
        this.mixer.clipAction(gltf.animations[0]).play();
      }
    } catch (err) {
      console.warn('проводник не загрузился', err);
    }
  }

  update(state) {
    this.stateData = state;
    for (const data of state.stations) this.nodes.get(data.id)?.set(data);
  }

  onPick(callback) { this._picked = callback; }
  setState(value) { this.state = value; }
  setLevel(value) { this.level = clamp(value, 0, 1); }

  /**
   * Ведёт камеру.
   *
   * Полтора-два кадра секунды — время подобрано под речь, а не под зрелищность.
   * Камера обязана прийти на место чуть раньше, чем голос назовёт участок:
   * пришла позже — зритель услышал вывод, глядя не туда, и связь между словом
   * и местом не возникла.
   */
  focus(stationId, mode = 'dive') {
    const node = stationId ? this.nodes.get(stationId) : null;
    this.focused = (mode === 'wide' || mode === 'sweep' || mode === 'hero') ? null : (stationId || null);

    let to, look, seconds = 1.5;
    if (mode === 'hero') {
      to = new THREE.Vector3(GUIDE.x + 4.6, 2.7, GUIDE.z + 6.4);
      look = new THREE.Vector3(GUIDE.x, 2.4, GUIDE.z);
      seconds = 2.2;
    } else if (!node || mode === 'wide') {
      // Кадр строится по крайним точкам: проводник слева на отметке −11 и
      // отгрузка справа на 10,8. Камера низкая: вид сверху превращает цех в
      // карту, а фигуру — в макушку.
      to = new THREE.Vector3(-3.5, 6.4, 25.0);
      look = new THREE.Vector3(-1.0, 1.6, 0);
      seconds = 2.4;
    } else if (mode === 'sweep') {
      to = new THREE.Vector3(-15.5, 3.4, 8.0);
      look = new THREE.Vector3(4, 1.4, -0.5);
      seconds = 2.2;
    } else {
      const at = new THREE.Vector3(...node.data.position);
      const side = at.x < 1 ? 1 : -1;
      to = new THREE.Vector3(at.x + side * 3.0, 2.1, at.z + 4.8);
      look = new THREE.Vector3(at.x, 1.2, at.z);
      seconds = mode === 'orbit' ? 1.3 : 1.6;
    }
    this.orbit = mode === 'orbit' ? { at: new THREE.Vector3(...(node?.data.position || [0, 0, 0])) } : null;
    this.shot = {
      fromPos: this.camera.position.clone(), toPos: to,
      fromLook: this.look.clone(), toLook: look,
      t: 0, seconds,
    };
  }

  _resize() {
    const width = this.canvas.parentElement.clientWidth || 960;
    const height = this.canvas.parentElement.clientHeight || 600;
    this.renderer.setSize(width, height, false);
    this.composer.setSize(width, height);
    this.bloom.resolution.set(width, height);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  _pick(event) {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.ray.setFromCamera(this.pointer, this.camera);
    const targets = [...this.nodes.values()].map((node) => node.hit);
    const hit = this.ray.intersectObjects(targets, false)[0];
    if (hit) this._picked(hit.object.userData.station);
  }

  _tags() {
    const spot = new THREE.Vector3();
    const width = this.canvas.clientWidth, height = this.canvas.clientHeight;
    for (const node of this.nodes.values()) {
      if (!node.tag) continue;
      spot.set(...node.data.position);
      spot.y += clamp(node.load, 0.06, 1.05) * 3.6 + 0.5;
      spot.project(this.camera);
      const visible = spot.z < 1 && Math.abs(spot.x) < 1.3 && Math.abs(spot.y) < 1.3;
      const style = node.tag.style;
      if (!visible) { style.opacity = '0'; continue; }
      style.transform = `translate(-50%,-100%) translate(${(spot.x * 0.5 + 0.5) * width}px,${(-spot.y * 0.5 + 0.5) * height}px)`;
      style.opacity = String(clamp(node.dim, 0.12, 1));
      const gauge = node.tag.querySelector('[data-load]');
      const load = Math.round(node.load * 100);
      gauge.textContent = `${load}%`;
      gauge.className = node.load >= 0.98 ? 'crit' : node.load >= 0.9 ? 'warn' : '';
      node.tag.classList.toggle('hot', node.load >= 0.9);
    }
  }

  _frame() {
    const now = performance.now() / 1000;
    const dt = Math.min(now - this._last, 0.05);
    this._last = now;
    this._time += dt;
    const time = this._time;

    if (this.shot) {
      this.shot.t = clamp(this.shot.t + dt / this.shot.seconds, 0, 1);
      // Замедление к концу, а не симметричное: кадр должен мягко встать, а не
      // подъехать и замереть. Так движение читается как работа оператора.
      const k = this.shot.seconds > 2 ? easeOut(this.shot.t) : ease(this.shot.t);
      this.camera.position.lerpVectors(this.shot.fromPos, this.shot.toPos, k);
      this.look.lerpVectors(this.shot.fromLook, this.shot.toLook, k);
      if (this.shot.t >= 1) this.shot = null;
    } else if (this.orbit) {
      const radius = 5.6;
      this.camera.position.set(
        this.orbit.at.x + Math.cos(time * 0.22) * radius, 2.4,
        this.orbit.at.z + Math.sin(time * 0.22) * radius,
      );
      this.look.set(this.orbit.at.x, 1.2, this.orbit.at.z);
    } else {
      // Камера всё время едва заметно дышит: полная неподвижность читается как
      // стоп-кадр, и сцена перестаёт восприниматься живой.
      this.camera.position.y += Math.sin(time * 0.45) * 0.0014;
      this.camera.position.x += Math.cos(time * 0.31) * 0.0011;
    }
    this.camera.lookAt(this.look);

    for (const node of this.nodes.values()) node.step(dt, time, this.focused, this.camera);
    for (const flow of this.flows) {
      const source = this.nodes.get(flow.from);
      // Искры замедляются перед перегруженным участком и скучиваются там же:
      // скорость потока — это и есть пропускная способность узкого места.
      const brake = source ? clamp(1.15 - source.load, 0.1, 1) : 1;
      const dim = this.focused ? (flow.from === this.focused ? 1 : 0.22) : 0.7;
      flow.step(dt, 0.08 + brake * 0.2, dim);
    }

    if (this.mixer) {
      this.mixer.timeScale = this.state === 'speaking' ? 1.05 : 1.0;
      this.mixer.update(dt);
    }
    if (this.guide) {
      this.guide.position.y = this.guideBase ?? (this.guideBase = this.guide.position.y);
      this.guide.position.y += Math.sin(time * 0.85) * 0.012;
    }
    if (this.aura) {
      const want = this.state === 'speaking' ? 3.2 + this.level * 9.0
                 : this.state === 'thinking' ? 2.4 + Math.sin(time * 4) * 1.0 : 1.6;
      this.aura.intensity += (want - this.aura.intensity) * 0.12;
    }
    if (this.daisEdge) {
      this.daisEdge.material.opacity = 0.55 + (this.state === 'speaking' ? this.level * 0.4 : 0.1 * Math.sin(time * 1.4) + 0.1);
    }
    this.bloom.strength = 0.5 + (this.state === 'speaking' ? this.level * 0.22 : 0);

    this._tags();
    this.composer.render();
  }
}
