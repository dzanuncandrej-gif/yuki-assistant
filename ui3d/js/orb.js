/**
 * «Ядро» Юки: рой частиц, который перестраивается под состояние ассистента.
 *
 *   ожидание  — сфера, дышит
 *   слушает   — звуковая волна, качается от уровня микрофона
 *   думает    — нейросеть из узлов и связей
 *   действует — стена кубов, по одному на инструмент
 *   говорит   — сфера, пульсирует от громкости собственной речи
 *
 * Та же сцена, что на сайте проекта, только размер берётся от контейнера,
 * а не от окна: ядро живёт и в пульте, и во весь экран звонка.
 */
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';

import { buildRings, buildShapes, buildStars } from './shapes.js';

const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1./6.,1./3.);const vec4 D=vec4(0.,.5,1.,2.);
  vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.-g;vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
  float n_=.142857142857;vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.*x_);
  vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.+1.;vec4 s1=floor(b1)*2.+1.;vec4 sh=-step(h,vec4(0.));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);m=m*m;
  return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

const SWARM_VERT = /* glsl */ `
uniform float uTime, uMorph, uAmp, uSize, uPR, uDim, uFlash, uMouseF, uHue;
uniform vec3 uMouse;
attribute vec3 p1; attribute vec3 p2; attribute vec3 p3; attribute vec3 p4;
attribute vec4 aRnd;
varying vec3 vCol; varying float vA;
${NOISE}
float stage(float k){ return smoothstep(0., 1., clamp((uMorph - (k - 1.)) * 1.7 - aRnd.x * 0.7, 0., 1.)); }
void main(){
  float t1 = stage(1.), t2 = stage(2.), t3 = stage(3.), t4 = stage(4.);
  vec3 p = position;
  p = mix(p, p1, t1); p = mix(p, p2, t2); p = mix(p, p3, t3); p = mix(p, p4, t4);
  float PI = 3.14159265;
  float fly = sin(PI * t1) + sin(PI * t2) + sin(PI * t3) + sin(PI * t4);
  float w0 = 1. - t1, w1 = t1 * (1. - t2), w2 = t2 * (1. - t3), w3 = t3 * (1. - t4), w4 = t4;

  float tt = uTime * 0.22;
  vec3 q = p * 0.42;
  vec3 n = vec3(snoise(q + vec3(tt, 0., 0.)), snoise(q + vec3(0., tt, 17.)), snoise(q + vec3(31., 0., tt)));
  p += n * (0.045 + fly * 1.05);

  vec3 dir = normalize(p + 1e-4);
  float wob = snoise(dir * 1.9 + vec3(0., 0., uTime * 0.9));
  p += dir * uAmp * (0.5 + 0.7 * wob) * (w0 + w2 * 0.45 + w4 * 0.35);
  p *= 1. + 0.018 * sin(uTime * 1.25) * w0;
  p.y += w1 * sin(p.x * 1.25 - uTime * 2.4 + p.z * 0.9) * (0.14 + uAmp * 1.6);
  p.z += w3 * sin(uTime * 1.6 + floor((p.x + 3.3) / 0.6) * 0.9 + floor((p.y + 2.4) / 0.6) * 1.7) * 0.06;

  vec4 mv = modelViewMatrix * vec4(p, 1.);
  vec2 d = mv.xy - uMouse.xy; float dl = length(d);
  mv.xy += (d / (dl + 1e-4)) * exp(-dl * dl * 1.5) * uMouseF * 0.7;
  gl_Position = projectionMatrix * mv;

  float tw = 0.62 + 0.38 * sin(uTime * (0.8 + aRnd.z * 3.) + aRnd.w * 6.2832);
  gl_PointSize = uSize * (0.5 + aRnd.y * 0.95) * (1. + uAmp * 0.5) * uPR * (10. / -mv.z);

  vec3 cA = mix(vec3(0.30, 0.66, 1.0), vec3(1.0, 0.62, 0.36), uHue);
  vec3 cB = mix(vec3(0.52, 0.38, 1.0), vec3(1.0, 0.36, 0.52), uHue);
  vec3 cW = vec3(0.86, 0.93, 1.0);
  float g = clamp(0.5 + p.y * 0.2 - p.x * 0.06 + (aRnd.z - 0.5) * 0.55, 0., 1.);
  vec3 col = mix(cA, cB, g);
  col = mix(col, cW, clamp(smoothstep(0.94, 1., aRnd.w) + uFlash * 0.55 + uAmp * 0.35 * w0 + fly * 0.12, 0., 1.));
  vCol = col;
  vA = tw * uDim * (0.5 + 0.5 * aRnd.y) * (1. + w3 * 0.2) * 0.85;
}`;

const SWARM_FRAG = /* glsl */ `
varying vec3 vCol; varying float vA;
void main(){
  float a = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
  a *= a;
  gl_FragColor = vec4(vCol * a * vA, a * vA);
}`;

const RING_VERT = /* glsl */ `
uniform float uTime, uPR, uAlpha, uAmp;
attribute vec2 aMeta;
varying float vA; varying float vRing;
void main(){
  float ring = aMeta.x;
  float speed = ring == 0. ? 0.05 : ring == 1. ? -0.09 : 0.03;
  float a = uTime * speed;
  vec3 p = position;
  p.xy = mat2(cos(a), -sin(a), sin(a), cos(a)) * p.xy;
  p.xy *= 1. + uAmp * 0.06 * (ring + 1.);
  vec4 mv = modelViewMatrix * vec4(p, 1.);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = (ring == 2. ? 1.6 : 1.9) * uPR * (10. / -mv.z);
  float scan = 0.55 + 0.45 * sin(atan(p.y, p.x) * 2. - uTime * (0.6 + ring * 0.4));
  vA = uAlpha * scan * (ring == 0. ? 0.45 : 0.7);
  vRing = ring;
}`;

const RING_FRAG = /* glsl */ `
varying float vA; varying float vRing;
void main(){
  float a = smoothstep(0.5, 0.1, length(gl_PointCoord - 0.5));
  vec3 col = mix(vec3(0.35, 0.72, 1.0), vec3(0.6, 0.48, 1.0), vRing * 0.5);
  gl_FragColor = vec4(col * a * vA, a * vA);
}`;

const STAR_VERT = /* glsl */ `
uniform float uTime, uPR;
varying float vA;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.);
  gl_Position = projectionMatrix * mv;
  float h = fract(sin(dot(position.xy, vec2(12.9898, 78.233))) * 43758.5453);
  gl_PointSize = (1. + h * 1.6) * uPR;
  vA = (0.25 + 0.5 * h) * (0.6 + 0.4 * sin(uTime * (0.5 + h * 2.) + h * 40.));
}`;

const STAR_FRAG = /* glsl */ `
varying float vA;
void main(){
  float a = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
  gl_FragColor = vec4(vec3(0.7, 0.8, 1.0) * a * vA, a * vA);
}`;

const LensShader = {
  uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uGlitch: { value: 0 }, uBg: { value: new THREE.Color(0x03050b) } },
  vertexShader: /* glsl */ `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse; uniform float uTime, uGlitch; uniform vec3 uBg;
    varying vec2 vUv;
    float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
    void main(){
      vec2 uv = vUv;
      float band = step(0.985, hash(vec2(floor(uv.y * 60.), floor(uTime * 12.)))) * uGlitch;
      uv.x += band * (hash(vec2(uTime, uv.y)) - 0.5) * 0.06;
      vec2 c = uv - 0.5;
      float k = 0.0022 * (0.4 + dot(c, c) * 3.) + uGlitch * 0.006;
      vec3 col;
      col.r = texture2D(tDiffuse, uv + c * k).r;
      col.g = texture2D(tDiffuse, uv).g;
      col.b = texture2D(tDiffuse, uv - c * k * 1.2).b;
      col = uBg + col * smoothstep(1.1, 0.3, length(c * vec2(1.0, 1.15)));
      col += (hash(uv * 900. + fract(uTime * 7.)) - 0.5) * 0.022;
      gl_FragColor = vec4(col, 1.);
    }`,
};

// morph — форма, x/y — смещение в долях половины кадра, dim — яркость, rings — кольца
export const PRESETS = {
  idle: { morph: 0, dim: 0.9, rings: 1, hue: 0 },
  listening: { morph: 1, dim: 1, rings: 0.3, hue: 0 },
  thinking: { morph: 2, dim: 1, rings: 0, hue: 0 },
  acting: { morph: 3, dim: 1.05, rings: 0, hue: 0 },
  speaking: { morph: 0, dim: 1.05, rings: 1, hue: 0 },
  greeting: { morph: 4, dim: 1.1, rings: 0, hue: 0 },
  error: { morph: 0, dim: 1, rings: 0.4, hue: 1 },
  muted: { morph: 0, dim: 0.35, rings: 0.2, hue: 0 },
};

function points(geo, vert, frag, uniforms) {
  const mesh = new THREE.Points(geo, new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, uniforms,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  mesh.frustumCulled = false;
  return mesh;
}

const lerp = (a, b, t) => a + (b - a) * t;

export function createOrb(canvas, { count = 42000, zoom = 11, background = 0x03050b, size = 1 } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
  const pr = Math.min(window.devicePixelRatio || 1, 1.25);
  renderer.setPixelRatio(pr);
  renderer.setClearColor(0x000000, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 120);
  camera.position.set(0, 0, zoom);

  const { shapes, rnd } = buildShapes(count);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(shapes[0], 3));
  shapes.slice(1).forEach((arr, i) => geo.setAttribute(`p${i + 1}`, new THREE.BufferAttribute(arr, 3)));
  geo.setAttribute('aRnd', new THREE.BufferAttribute(rnd, 4));
  const swarm = points(geo, SWARM_VERT, SWARM_FRAG, {
    uTime: { value: 0 }, uMorph: { value: 0 }, uAmp: { value: 0 }, uSize: { value: (count > 30000 ? 3.1 : 3.8) * size },
    uPR: { value: pr }, uDim: { value: 1 }, uFlash: { value: 0 }, uMouseF: { value: 0 }, uHue: { value: 0 },
    uMouse: { value: new THREE.Vector3(99, 99, 0) },
  });

  const ringData = buildRings();
  const ringGeo = new THREE.BufferGeometry();
  ringGeo.setAttribute('position', new THREE.BufferAttribute(ringData.positions, 3));
  ringGeo.setAttribute('aMeta', new THREE.BufferAttribute(ringData.meta, 2));
  const rings = points(ringGeo, RING_VERT, RING_FRAG, { uTime: { value: 0 }, uPR: { value: pr }, uAlpha: { value: 1 }, uAmp: { value: 0 } });

  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute('position', new THREE.BufferAttribute(buildStars(1600), 3));
  const stars = points(starGeo, STAR_VERT, STAR_FRAG, { uTime: { value: 0 }, uPR: { value: pr } });

  const rig = new THREE.Group();
  rig.add(swarm, rings);
  scene.add(rig, stars);

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.9, 0.55, 0.08);
  composer.addPass(bloom);
  const lens = new ShaderPass(LensShader);
  lens.uniforms.uBg.value = new THREE.Color(background);
  composer.addPass(lens);

  const target = { morph: 0, x: 0, y: 0, scale: 1, dim: 0.9, rings: 1, amp: 0, flash: 0, glitch: 0, hue: 0 };
  const state = { ...target };
  const pointer = { x: 0, y: 0, sx: 0, sy: 0, active: 0 };

  function resize() {
    const w = Math.max(1, canvas.clientWidth); const h = Math.max(1, canvas.clientHeight);
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    camera.aspect = w / h;
    camera.position.z = zoom * (w / h < 0.9 ? 1.35 : 1);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  canvas.addEventListener('pointermove', (e) => {
    const r = canvas.getBoundingClientRect();
    pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    pointer.active = 1;
  });
  canvas.addEventListener('pointerleave', () => { pointer.active = 0; });

  const mouse = new THREE.Vector3();
  let last = performance.now();
  let time = 0;
  let running = true;
  // Потолок кадров. Замер 30.09.2026: облегчённое ядро на 60 кадрах почти не
  // влияет на скорость модели, а 10–30 кадров глаз видит как рывки.
  let fps = 60;

  function frame() {
    if (!running) return;
    requestAnimationFrame(frame);
    const now = performance.now();
    // на полной частоте кадр рисуется каждый раз: пропуски на мониторе 144 Гц давали дрожание
    if (fps < 60 && now - last < 1000 / fps - 2) return;
    const dt = Math.min((now - last) / 1000, 0.12);
    last = now;
    time += dt;
    const kSlow = 1 - Math.pow(0.08, dt);

    for (const key of ['morph', 'x', 'y', 'scale', 'dim', 'rings', 'hue']) state[key] = lerp(state[key], target[key], kSlow);
    state.amp = lerp(state.amp, target.amp, target.amp > state.amp ? 0.35 : 0.08);
    state.flash = lerp(state.flash, target.flash, 0.12);
    state.glitch = lerp(state.glitch, target.glitch, 0.2);
    target.flash *= 0.95;
    target.glitch *= 0.9;
    pointer.sx = lerp(pointer.sx, pointer.x * pointer.active, 0.05);
    pointer.sy = lerp(pointer.sy, pointer.y * pointer.active, 0.05);

    const halfH = Math.tan((camera.fov * Math.PI) / 360) * camera.position.z;
    rig.position.set(state.x * halfH * camera.aspect, state.y * halfH, 0);
    rig.scale.setScalar(state.scale);
    rig.rotation.y = Math.sin(time * 0.13) * 0.42 + pointer.sx * 0.35;
    rig.rotation.x = -pointer.sy * 0.22 + Math.sin(time * 0.3) * 0.05;
    rings.rotation.set(0.35 - rig.rotation.x * 0.5, -rig.rotation.y + 0.25, 0);
    stars.rotation.y = time * 0.01;

    mouse.set(pointer.x * halfH * camera.aspect, pointer.y * halfH, 0).applyMatrix4(camera.matrixWorldInverse);
    const u = swarm.material.uniforms;
    u.uTime.value = time; u.uMorph.value = state.morph; u.uAmp.value = state.amp;
    u.uDim.value = state.dim; u.uFlash.value = state.flash; u.uHue.value = state.hue;
    u.uMouse.value.copy(mouse);
    u.uMouseF.value = lerp(u.uMouseF.value, pointer.active, 0.05);
    const ru = rings.material.uniforms;
    ru.uTime.value = time; ru.uAlpha.value = state.rings * state.dim; ru.uAmp.value = state.amp;
    stars.material.uniforms.uTime.value = time;
    bloom.strength = 0.8 + state.amp * 0.9 + state.flash * 0.6;
    lens.uniforms.uTime.value = time;
    lens.uniforms.uGlitch.value = state.glitch;

    composer.render();
  }
  requestAnimationFrame(frame);

  return {
    target,
    state,
    /** Переводит ядро в состояние ассистента: форма, яркость, кольца. */
    mode(name) {
      const preset = PRESETS[name] || PRESETS.idle;
      Object.assign(target, preset);
    },
    pulse(strength = 1) {
      target.flash = Math.max(target.flash, strength);
      target.glitch = Math.max(target.glitch, strength * 0.8);
    },
    place(x = 0, y = 0, scale = 1) { Object.assign(target, { x, y, scale }); },
    /** Сколько кадров в секунду рисовать: меньше — больше видеокарты модели. */
    setFps(value) { fps = Math.max(4, Math.min(60, value)); },
    pause(paused) {
      if (paused) { running = false; return; }
      if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); }
    },
  };
}
