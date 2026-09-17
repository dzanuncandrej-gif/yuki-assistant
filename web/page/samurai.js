/**
 * Сцена самурая для сайта.
 *
 * У модели нет ни лицевых морфов, ни костей головы и челюсти — проверено по
 * файлу: девяносто шесть костей, и все они на теле, руках и одежде. Значит ни
 * мимики, ни движения губ сделать нельзя, и притворяться нечем.
 *
 * Поэтому «живость» здесь строится на том, что есть: собственная анимация
 * модели, дыхание корпуса, доворот к курсору и отклик на речь через свет и
 * лёгкое усиление движения. Это честнее, чем дёргать статичное лицо.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const CLAMP = (v, a, b) => Math.max(a, Math.min(b, v));

export class Samurai {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.framing = options.framing || 'full';
    this.state = 'idle';
    this.level = 0;
    this.pointer = { x: 0, y: 0 };
    this.aim = { x: 0, y: 0 };
    this.clock = new THREE.Clock();
    this.ready = false;
    this._build();
  }

  _build() {
    const renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: true, alpha: true, powerPreference: 'high-performance',
    });
    // Ограничение плотности пикселей — главный рычаг производительности.
    // На экране с плотностью три сцена считается вдевятеро дороже, чем на
    // обычном, а разницы почти не видно: модель небольшая и стоит далеко.
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.shadowMap.enabled = false;   // теней нет: персонаж висит на фоне сайта
    this.renderer = renderer;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);

    // Свет ставится как в студии: ключевой тёплый спереди-сбоку, холодный
    // контровой сзади — он отделяет силуэт от тёмного фона, — и мягкая заливка.
    const key = new THREE.DirectionalLight(0xfff0dc, 3.0);
    key.position.set(2.4, 3.2, 3.0);
    const rim = new THREE.DirectionalLight(0x8fb6ff, 3.2);
    rim.position.set(-2.6, 2.4, -2.4);
    const fill = new THREE.DirectionalLight(0xffd9a8, 0.7);
    fill.position.set(-1.6, 0.6, 2.2);
    this.accent = new THREE.PointLight(0xc8102e, 0.0, 6, 2);
    this.accent.position.set(0, 1.3, 1.4);
    this.scene.add(key, rim, fill, this.accent, new THREE.HemisphereLight(0x9ab4dd, 0x120c08, 0.5));

    this.root = new THREE.Group();
    this.scene.add(this.root);

    // Окружение из простого градиента. Без него металл доспеха и клинка выглядит
    // плоской заливкой: физическому материалу нужно что-то, что он отражает.
    this._environment();
    this._dust();

    this._resize();
    window.addEventListener('resize', () => this._resize());
    this.renderer.setAnimationLoop(() => this._frame());
  }

  /** Отражения: маленькая градиентная карта вместо тяжёлого HDRI. */
  _environment() {
    const canvas = document.createElement('canvas');
    canvas.width = 4; canvas.height = 128;
    const paint = canvas.getContext('2d');
    const grad = paint.createLinearGradient(0, 0, 0, 128);
    grad.addColorStop(0.0, '#2a3550');
    grad.addColorStop(0.45, '#0d1322');
    grad.addColorStop(0.62, '#3a2118');
    grad.addColorStop(1.0, '#05070c');
    paint.fillStyle = grad; paint.fillRect(0, 0, 4, 128);
    const texture = new THREE.CanvasTexture(canvas);
    texture.mapping = THREE.EquirectangularReflectionMapping;
    texture.colorSpace = THREE.SRGBColorSpace;
    this.scene.environment = texture;
  }

  /** Пылинки в луче света: сцена перестаёт быть стерильной. */
  _dust() {
    const count = 120;
    const spots = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      spots[i * 3] = (Math.random() - 0.5) * 2.6;
      spots[i * 3 + 1] = Math.random() * 2.4;
      spots[i * 3 + 2] = (Math.random() - 0.5) * 2.0;
    }
    const shape = new THREE.BufferGeometry();
    shape.setAttribute('position', new THREE.BufferAttribute(spots, 3));
    this.dust = new THREE.Points(shape, new THREE.PointsMaterial({
      color: 0xc9a227, size: 0.012, transparent: true, opacity: 0.5,
      depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    this.scene.add(this.dust);
  }

  async load(url) {
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(url);
    const model = gltf.scene;

    // Модель приходит в своих единицах и своём положении. Считаем габариты и
    // нормализуем: иначе персонаж окажется то в пикселе, то за пределами кадра.
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    const scale = 2.0 / Math.max(size.y, 0.001);   // крупнее в кадре
    model.scale.setScalar(scale);
    model.position.set(-centre.x * scale, -box.min.y * scale, -centre.z * scale);

    model.traverse((node) => {
      if (!node.isMesh) return;
      node.frustumCulled = true;
      const material = node.material;
      if (material) {
        // Доспех и клинок должны читаться как металл. Модель приходит с плоскими
        // значениями, и без подъёма отражений самурай выглядит пластмассовым.
        material.envMapIntensity = 2.0;
        if (material.metalness !== undefined) {
          material.metalness = Math.min(1, (material.metalness ?? 0) + 0.25);
        }
        if (material.roughness !== undefined) {
          material.roughness = Math.max(0.08, (material.roughness ?? 1) * 0.78);
        }
        if (material.map) material.map.anisotropy = 8;
      }
    });

    this.root.add(model);
    this.model = model;
    this.height = size.y * scale;

    if (gltf.animations?.length) {
      this.mixer = new THREE.AnimationMixer(model);
      this.action = this.mixer.clipAction(gltf.animations[0]);
      this.action.play();
    }
    this._frameCamera();
    this.ready = true;
    return this;
  }

  _frameCamera() {
    // Камера чуть ниже пояса и ближе, чем «правильный» ростовой кадр. Съёмка
    // снизу делает фигуру внушительной — приём из кино, и для воина он уместен.
    // Прежний кадр был честным, но персонаж выглядел мелкой фигуркой в углу.
    const plans = {
      full: { y: 0.72, z: 3.5, look: 1.05 },
      bust: { y: 1.32, z: 2.1, look: 1.36 },
      close: { y: 1.5, z: 1.25, look: 1.5 },
    };
    const plan = plans[this.framing] || plans.full;
    this.camera.position.set(0, plan.y, plan.z);
    this.lookAt = new THREE.Vector3(0, plan.look, 0);
    this.camera.lookAt(this.lookAt);
  }

  _resize() {
    const box = this.canvas.parentElement || this.canvas;
    const width = box.clientWidth || 400;
    const height = box.clientHeight || 600;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  /** Курсор в пределах окна: персонаж слегка доворачивается к нему. */
  track(x, y) {
    this.pointer.x = CLAMP(x, -1, 1);
    this.pointer.y = CLAMP(y, -1, 1);
  }

  setState(state) { this.state = state; }
  setLevel(value) { this.level = CLAMP(value, 0, 1); }

  _frame() {
    const delta = Math.min(this.clock.getDelta(), 0.05);
    const time = this.clock.elapsedTime;
    if (this.mixer) {
      // во время речи движение чуть живее — говорящий человек не стоит столбом
      this.mixer.timeScale = this.state === 'speaking' ? 1.08 : 1.0;
      this.mixer.update(delta);
    }

    if (this.root) {
      // доворот к курсору — плавный, с запаздыванием, иначе выглядит дёргано
      this.aim.x += (this.pointer.x * 0.22 - this.aim.x) * 0.055;
      this.aim.y += (this.pointer.y * 0.10 - this.aim.y) * 0.055;
      const breath = Math.sin(time * 0.9) * 0.012;
      const pulse = this.state === 'speaking' ? this.level * 0.02 : 0;
      this.root.rotation.y = this.aim.x;
      this.root.rotation.x = -this.aim.y * 0.5;
      this.root.position.y = breath + pulse;
    }

    if (this.dust) {
      this.dust.rotation.y = time * 0.045;
      this.dust.position.y = Math.sin(time * 0.35) * 0.06;
      this.dust.material.opacity = 0.32 + (this.state === 'speaking' ? this.level * 0.4 : 0.1);
    }

    // Красный контровой свет отзывается на речь. Мимики нет, поэтому именно свет
    // сообщает, что персонаж сейчас говорит, — и делает это заметно.
    const wanted = this.state === 'speaking' ? 2.2 + this.level * 5.0
                 : this.state === 'thinking' ? 1.0 + Math.sin(time * 4) * 0.5
                 : 0.35;
    this.accent.intensity += (wanted - this.accent.intensity) * 0.14;

    this.renderer.render(this.scene, this.camera);
  }

  /** Освобождает видеопамять, когда сцена больше не нужна. */
  dispose() {
    this.renderer.setAnimationLoop(null);
    this.scene.traverse((node) => {
      if (node.isMesh) {
        node.geometry?.dispose();
        const list = Array.isArray(node.material) ? node.material : [node.material];
        list.forEach((material) => {
          Object.values(material || {}).forEach((value) => {
            if (value && value.isTexture) value.dispose();
          });
          material?.dispose?.();
        });
      }
    });
    this.renderer.dispose();
  }
}
