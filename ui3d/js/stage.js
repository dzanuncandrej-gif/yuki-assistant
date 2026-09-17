/**
 * Сцена: рендер, свет, камера, пыль в воздухе и киношная постобработка.
 *
 * Всё, что не связано с самим персонажем, живёт здесь. Сцена держит тёмный
 * тон интерфейса: холодный ключевой свет, синий контровой, мягкое свечение и
 * лёгкая виньетка с зерном — чтобы кадр выглядел снятым, а не отрисованным.
 */

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

export const ACCENT = {
  idle: new THREE.Color(0x7fb2ff),
  listening: new THREE.Color(0x69e2ff),
  thinking: new THREE.Color(0xa88cff),
  speaking: new THREE.Color(0x8fd8ff),
  success: new THREE.Color(0x6ff0c0),
  error: new THREE.Color(0xff7a94),
};

/** Виньетка, зерно и микро-аберрация: три копеечных приёма, дающих «кино». */
const GradeShader = {
  uniforms: {
    tDiffuse: { value: null },
    time: { value: 0 },
    vignette: { value: 0.95 },
    grain: { value: 0.016 },
    aberration: { value: 0.0016 },
    tint: { value: new THREE.Color(0x7fb2ff) },
    tintAmount: { value: 0.05 },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
  `,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform float time, vignette, grain, aberration, tintAmount;
    uniform vec3 tint;
    varying vec2 vUv;

    float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

    void main() {
      vec2 centred = vUv - 0.5;
      float radius = length(centred);
      // канал за каналом: к краям кадра цвета чуть расходятся, как в оптике
      vec2 shift = centred * aberration * radius;
      vec3 color = vec3(
        texture2D(tDiffuse, vUv + shift).r,
        texture2D(tDiffuse, vUv).g,
        texture2D(tDiffuse, vUv - shift).b
      );
      color = mix(color, color * tint * 1.6, tintAmount);
      color *= 1.0 - vignette * pow(radius, 2.6) * 0.85;
      color += (hash(vUv * 900.0 + fract(time)) - 0.5) * grain;
      gl_FragColor = vec4(color, texture2D(tDiffuse, vUv).a);
    }
  `,
};

export class Stage {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.transparent = Boolean(options.transparent);
    this.quality = options.quality || 'high';

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: this.quality !== 'low',
      alpha: this.transparent,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: Boolean(options.capture),
    });
    this.renderer.setClearColor(0x000000, this.transparent ? 0 : 1);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.98;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(28, 1, 0.05, 60);
    this.camera.position.set(0, 1.42, 1.95);
    // куда смотрит камера и откуда: между планами она переезжает плавно
    this.focus = new THREE.Vector3(0, 1.28, 0);
    this._focusTarget = this.focus.clone();
    this._eyeTarget = this.camera.position.clone();
    this.manualCamera = false;

    this.accent = ACCENT.idle.clone();
    this._accentTarget = ACCENT.idle.clone();
    this._time = 0;

    this._buildLights();
    if (!this.transparent) this._buildBackdrop();
    this._buildDust();
    this._buildComposer();
    this.resize();

    // окно приложения меняет размер без события resize (док, компактный режим),
    // поэтому следим за самим контейнером
    const parent = canvas.parentElement;
    if (parent && typeof ResizeObserver !== 'undefined') {
      this._observer = new ResizeObserver(() => this.resize());
      this._observer.observe(parent);
    }
  }

  // ------------------------------------------------------------------ свет

  _buildLights() {
    // сел-шейдинг реагирует на свет резче, чем PBR: яркости здесь заметно
    // ниже привычных, иначе лицо выгорает в белое пятно
    this.ambient = new THREE.HemisphereLight(0x8fb6ff, 0x0a1020, 0.42);
    this.scene.add(this.ambient);

    this.key = new THREE.DirectionalLight(0xfff4e8, 1.15);
    this.key.position.set(1.7, 3.0, 2.4);
    this.scene.add(this.key);

    this.fill = new THREE.DirectionalLight(0x6fa8ff, 0.34);
    this.fill.position.set(-2.4, 1.5, 1.4);
    this.scene.add(this.fill);

    // контровой цвет меняется вместе с состоянием ассистента
    this.rim = new THREE.DirectionalLight(this.accent.getHex(), 0.85);
    this.rim.position.set(-1.4, 2.4, -2.6);
    this.scene.add(this.rim);

    this.faceLight = new THREE.PointLight(0xdce9ff, 0.55, 3.2, 2.0);
    this.faceLight.position.set(0.32, 1.58, 0.85);
    this.scene.add(this.faceLight);

    this.glow = new THREE.PointLight(this.accent.getHex(), 1.1, 3.4, 2.2);
    this.glow.position.set(0, 0.16, 0.55);
    this.scene.add(this.glow);
  }

  /** Фон: мягкий градиент и кольца пола, на которых стоит фигура. */
  _buildBackdrop() {
    const backdrop = new THREE.Mesh(
      new THREE.SphereGeometry(24, 32, 16),
      new THREE.ShaderMaterial({
        side: THREE.BackSide,
        depthWrite: false,
        uniforms: { accent: { value: this.accent } },
        vertexShader: `
          varying vec3 vPos;
          void main() { vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
        `,
        fragmentShader: `
          uniform vec3 accent;
          varying vec3 vPos;
          void main() {
            float h = normalize(vPos).y * 0.5 + 0.5;
            vec3 deep = vec3(0.012, 0.018, 0.032);
            vec3 near = mix(vec3(0.02, 0.035, 0.07), accent * 0.10, 0.55);
            gl_FragColor = vec4(mix(deep, near, pow(h, 1.6)), 1.0);
          }
        `,
      }),
    );
    this.scene.add(backdrop);
    this.backdrop = backdrop;

    this.rings = new THREE.Group();
    for (let i = 0; i < 3; i += 1) {
      const radius = 0.55 + i * 0.28;
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(radius, radius + 0.006, 128),
        new THREE.MeshBasicMaterial({
          color: this.accent, transparent: true, opacity: 0.5 - i * 0.13,
          side: THREE.DoubleSide, depthWrite: false, toneMapped: false,
        }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.002 + i * 0.001;
      this.rings.add(ring);
    }
    this.scene.add(this.rings);

    const pool = new THREE.Mesh(
      new THREE.CircleGeometry(1.5, 64),
      new THREE.ShaderMaterial({
        transparent: true, depthWrite: false,
        uniforms: { accent: { value: this.accent }, power: { value: 0.4 } },
        vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
        fragmentShader: `
          uniform vec3 accent; uniform float power; varying vec2 vUv;
          void main() {
            float d = length(vUv - 0.5) * 2.0;
            gl_FragColor = vec4(accent, (1.0 - smoothstep(0.0, 1.0, d)) * power);
          }
        `,
      }),
    );
    pool.rotation.x = -Math.PI / 2;
    this.scene.add(pool);
    this.pool = pool;
  }

  /** Пылинки в луче света — воздух вокруг фигуры перестаёт быть пустым. */
  _buildDust() {
    const count = this.quality === 'low' ? 220 : 620;
    const positions = new Float32Array(count * 3);
    const seeds = new Float32Array(count);
    for (let i = 0; i < count; i += 1) {
      positions[i * 3] = (Math.random() - 0.5) * 3.4;
      positions[i * 3 + 1] = Math.random() * 2.6;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 2.4;
      seeds[i] = Math.random();
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('seed', new THREE.BufferAttribute(seeds, 1));

    this.dust = new THREE.Points(geometry, new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { time: { value: 0 }, accent: { value: this.accent }, pixelRatio: { value: 1 } },
      vertexShader: `
        attribute float seed;
        uniform float time, pixelRatio;
        varying float vFade;
        void main() {
          vec3 p = position;
          p.y = mod(p.y + time * (0.04 + seed * 0.07), 2.6);
          p.x += sin(time * (0.25 + seed) + seed * 12.0) * 0.06;
          p.z += cos(time * (0.19 + seed) + seed * 8.0) * 0.05;
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vFade = smoothstep(0.0, 0.5, p.y) * (1.0 - smoothstep(1.7, 2.6, p.y)) * (0.35 + seed * 0.65);
          gl_PointSize = (1.4 + seed * 2.6) * pixelRatio * (2.6 / -mv.z);
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        uniform vec3 accent;
        varying float vFade;
        void main() {
          float d = length(gl_PointCoord - 0.5);
          if (d > 0.5) discard;
          gl_FragColor = vec4(accent, (1.0 - d * 2.0) * vFade * 0.55);
        }
      `,
    }));
    this.dust.frustumCulled = false;
    this.scene.add(this.dust);
  }

  _buildComposer() {
    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));

    if (this.quality !== 'low') {
      this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.22, 0.55, 0.92);
      this.composer.addPass(this.bloom);
    }
    this.grade = new ShaderPass(GradeShader);
    this.composer.addPass(this.grade);
    this.composer.addPass(new OutputPass());
  }

  // ------------------------------------------------------------------ работа

  setAccent(color) { this._accentTarget.set(color); }

  /**
   * Планы кадра. Камера переезжает между ними сама — резких склеек нет.
   *
   * Расстояние не задано числом, а считается от габаритов самой модели: у
   * другого персонажа другой рост, и жёстко подобранная точка обрезала бы ему
   * то ноги, то макушку.
   */
  setFraming(mode, zoom = 1) {
    this.framing = mode || 'full';
    this.zoom = zoom > 0 ? zoom : 1;
    this._applyFraming();
  }

  watch(object) {
    this.subject = object;
    this._applyFraming();
  }

  _applyFraming() {
    if (!this.subject) return;

    const box = new THREE.Box3().setFromObject(this.subject);
    if (box.isEmpty()) return;
    const centre = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const top = box.max.y;

    // сколько модели по вертикали должно попасть в кадр
    const spans = {
      full: [box.min.y, top],
      bust: [top - size.y * 0.56, top],
      close: [top - size.y * 0.26, top],
    };
    const [low, high] = spans[this.framing] || spans.full;
    const height = Math.max(0.05, high - low);
    const width = Math.max(0.05, Math.max(size.x, size.z));

    const fov = (this.camera.fov * Math.PI) / 180;
    // запас по краям: фигура не должна упираться в границы окна
    const margin = this.framing === 'full' ? 1.16 : 1.10;
    const byHeight = (height * margin * 0.5) / Math.tan(fov * 0.5);
    const byWidth = (width * margin * 0.5) / (Math.tan(fov * 0.5) * this.camera.aspect);
    const distance = Math.max(byHeight, byWidth) / this.zoom;

    const eyeY = (low + high) * 0.5 + height * 0.04;
    this._eyeTarget.set(centre.x + distance * 0.045, eyeY, distance);
    this._focusTarget.set(centre.x, eyeY, 0);
  }

  setQuality(quality) {
    if (quality === this.quality) return;
    this.quality = quality;
    this.resize();
  }

  resize() {
    const parent = this.canvas.parentElement || document.body;
    const width = Math.max(2, parent.clientWidth);
    const height = Math.max(2, parent.clientHeight);
    const cap = this.quality === 'low' ? 1 : (this.quality === 'medium' ? 1.35 : 1.9);
    const ratio = Math.min(window.devicePixelRatio || 1, cap);

    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(width, height, false);
    this.composer.setPixelRatio(ratio);
    this.composer.setSize(width, height);
    if (this.bloom) this.bloom.setSize(width, height);
    if (this.dust) this.dust.material.uniforms.pixelRatio.value = ratio;

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this._applyFraming();  // от пропорций окна зависит, откуда смотреть
  }

  /** Медленный наезд и лёгкий параллакс — кадр никогда не стоит намертво. */
  _updateCamera(delta) {
    if (this.manualCamera) return;
    const ease = 1 - Math.exp(-1.6 * delta);
    this.camera.position.lerp(this._eyeTarget, ease);
    this.focus.lerp(this._focusTarget, ease);
    const sway = Math.sin(this._time * 0.21) * 0.016 + Math.sin(this._time * 0.13) * 0.010;
    const rise = Math.sin(this._time * 0.17) * 0.008;
    this.camera.position.x += sway;
    this.camera.position.y += rise;
    this.camera.lookAt(this.focus);
  }

  render(delta) {
    this._time += delta;
    this._updateCamera(delta);
    this.accent.lerp(this._accentTarget, Math.min(1, delta * 2.4));

    this.rim.color.copy(this.accent);
    this.glow.color.copy(this.accent);
    this.glow.intensity = 2.4 + Math.sin(this._time * 1.1) * 0.5;
    if (this.dust) this.dust.material.uniforms.time.value = this._time;
    if (this.rings) {
      this.rings.rotation.y = this._time * 0.06;
      this.rings.children.forEach((ring, index) => {
        ring.material.opacity = (0.34 - index * 0.09) * (0.75 + 0.25 * Math.sin(this._time * 1.3 - index));
      });
    }
    this.grade.uniforms.time.value = this._time;
    this.grade.uniforms.tint.value.copy(this.accent);
    this.composer.render(delta);
  }

  dispose() {
    if (this._observer) this._observer.disconnect();
    this.renderer.dispose();
    this.composer.dispose();
  }
}
