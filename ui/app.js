/* Джарвис UI: WebGL2-сфера с рейммаршингом + websocket-мост к ассистенту.
   Без внешних библиотек — всё считает один фрагментный шейдер. */

(() => {
  "use strict";

  // ---------- шейдеры ----------

  const VERT = `#version 300 es
  precision highp float;
  const vec2 verts[3] = vec2[3](vec2(-1.0,-1.0), vec2(3.0,-1.0), vec2(-1.0,3.0));
  void main() { gl_Position = vec4(verts[gl_VertexID], 0.0, 1.0); }`;

  const FRAG = `#version 300 es
  precision highp float;
  out vec4 fragColor;

  uniform vec2  uRes;
  uniform float uTime;
  uniform float uLevel;
  uniform vec3  uCore;
  uniform vec3  uRim;
  uniform float uAmp;
  uniform float uSpeed;
  uniform float uNoise;
  uniform float uGlow;

  float hash(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }

  float vnoise(vec3 x) {
    vec3 i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(hash(i + vec3(0,0,0)), hash(i + vec3(1,0,0)), f.x),
          mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
          mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
  }

  float fbm(vec3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 4; i++) { s += a * vnoise(p); p *= 2.03; a *= 0.5; }
    return s;
  }

  mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

  float turb(vec3 p) {
    float t = uTime * uSpeed;
    vec3 q = p;
    q.xz *= rot(t * 0.25);
    q.xy *= rot(t * 0.17);
    return fbm(q * uNoise + vec3(0.0, t * 0.5, t * 0.3));
  }

  float map(vec3 p) {
    float n = turb(p);
    float r = 0.92 + uAmp * (n - 0.5) * 2.0;
    return (length(p) - r) * 0.55;
  }

  vec3 normalAt(vec3 p) {
    vec2 e = vec2(0.012, 0.0);
    return normalize(vec3(
      map(p + e.xyy) - map(p - e.xyy),
      map(p + e.yxy) - map(p - e.yxy),
      map(p + e.yyx) - map(p - e.yyx)));
  }

  void main() {
    vec2 uv = (gl_FragCoord.xy * 2.0 - uRes) / min(uRes.x, uRes.y);
    vec3 ro = vec3(0.0, 0.0, 3.9);
    vec3 rd = normalize(vec3(uv, -2.35));

    float t = 0.0, minD = 1e9;
    bool hit = false;
    vec3 p = ro;

    for (int i = 0; i < 88; i++) {
      p = ro + rd * t;
      float d = map(p);
      minD = min(minD, d);
      if (d < 0.0016) { hit = true; break; }
      t += d;
      if (t > 6.0) break;
    }

    // глубокий фон: градиент, звёздная пыль, орбитальное кольцо
    float horizon = clamp(uv.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 col = mix(vec3(0.0035, 0.0045, 0.009), vec3(0.008, 0.011, 0.024), horizon);

    vec2 cell = floor(uv * 46.0);
    float seed = hash(vec3(cell, 7.13));
    if (seed > 0.985) {
      vec2 local = fract(uv * 46.0) - 0.5;
      float twinkle = 0.55 + 0.45 * sin(uTime * 1.7 + seed * 40.0);
      col += vec3(0.55, 0.72, 1.0) * smoothstep(0.16, 0.0, length(local)) * twinkle * 0.42;
    }

    vec3 planeN = normalize(vec3(0.0, 1.0, 0.42));
    float denom = dot(rd, planeN);
    if (abs(denom) > 0.0015) {
      float tp = -dot(ro, planeN) / denom;
      if (tp > 0.0 && (!hit || tp < t)) {
        vec3 q = ro + rd * tp;
        float radius = length(q);
        float band = smoothstep(1.17, 1.23, radius) * smoothstep(1.46, 1.34, radius);
        float grain = 0.45 + 0.55 * fbm(q * 3.4 + vec3(0.0, uTime * uSpeed * 0.7, 0.0));
        col += uRim * band * grain * (0.42 + 0.55 * uLevel);
      }
    }

    if (hit) {
      vec3 n = normalAt(p);
      vec3 l = normalize(vec3(0.55, 0.75, 0.62));
      float diff = clamp(dot(n, l), 0.0, 1.0);
      float fres = pow(1.0 - max(dot(n, -rd), 0.0), 3.0);
      float spec = pow(max(dot(reflect(-l, n), -rd), 0.0), 56.0);

      // светятся только гребни шума — пятна энергии на тёмном теле
      float coarse = turb(p * 2.0);
      float fine = turb(p * 4.6 + 2.3);
      float glow = smoothstep(0.60, 0.92, coarse) + 0.55 * smoothstep(0.66, 0.95, fine);

      col = uCore * (0.035 + 0.10 * diff);
      col += mix(uCore, uRim, 0.55) * glow * (0.34 + 0.95 * uLevel);
      col += uRim * pow(fres, 1.25) * (2.10 + 1.30 * uLevel);
      col += vec3(1.0) * spec * 0.30;
    } else {
      float halo = exp(-max(minD, 0.0) * 10.0);
      col += uRim * halo * uGlow * (0.20 + 0.50 * uLevel);
    }

    // фоновое свечение и виньетка
    float r = length(uv);
    col += uCore * 0.018 / (r * r + 0.5);
    col *= 1.0 - 0.62 * smoothstep(0.35, 1.55, r);

    // тонмаппинг, возврат насыщенности, дизеринг против бандинга
    col = col / (col + vec3(1.05));
    col = pow(col, vec3(0.4545));
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = clamp(mix(vec3(lum), col, 1.35), 0.0, 1.0);
    col += (hash(vec3(gl_FragCoord.xy, uTime)) - 0.5) * 0.012;

    fragColor = vec4(col, 1.0);
  }`;

  // ---------- состояния ----------

  const PRESETS = {
    idle:      { core: [0.06, 0.26, 0.72], rim: [0.30, 0.72, 1.00], amp: 0.022, speed: 0.26, noise: 1.5, glow: 0.55 },
    listening: { core: [0.03, 0.62, 0.82], rim: [0.45, 1.00, 0.92], amp: 0.040, speed: 0.60, noise: 1.9, glow: 0.95 },
    thinking:  { core: [0.38, 0.12, 0.86], rim: [0.88, 0.50, 1.00], amp: 0.060, speed: 1.60, noise: 2.4, glow: 1.05 },
    speaking:  { core: [1.00, 0.36, 0.06], rim: [1.00, 0.74, 0.32], amp: 0.048, speed: 0.85, noise: 1.8, glow: 1.10 },
  };

  const LABEL = {
    idle: "ожидание",
    listening: "слушаю",
    thinking: "думаю",
    speaking: "говорю",
  };

  const params = { ...PRESETS.idle, core: [...PRESETS.idle.core], rim: [...PRESETS.idle.rim] };
  let target = PRESETS.idle;
  let level = 0;
  let levelTarget = 0;

  // ---------- WebGL ----------

  const canvas = document.getElementById("scene");
  const gl = canvas.getContext("webgl2", { antialias: false, alpha: false, powerPreference: "high-performance" });

  if (!gl) {
    document.body.insertAdjacentHTML("afterbegin",
      '<p style="position:fixed;inset:0;display:grid;place-items:center;color:#ff8f8f">WebGL2 недоступен в этом браузере.</p>');
    return;
  }

  function compile(type, src) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, src);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader) || "shader compile failed");
    }
    return shader;
  }

  const program = gl.createProgram();
  gl.attachShader(program, compile(gl.VERTEX_SHADER, VERT));
  gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) || "link failed");
  }
  gl.useProgram(program);
  gl.bindVertexArray(gl.createVertexArray());

  const U = {};
  for (const name of ["uRes", "uTime", "uLevel", "uCore", "uRim", "uAmp", "uSpeed", "uNoise", "uGlow"]) {
    U[name] = gl.getUniformLocation(program, name);
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(window.innerWidth * dpr));
    const h = Math.max(1, Math.floor(window.innerHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
    }
  }
  window.addEventListener("resize", resize, { passive: true });
  resize();

  const lerp = (a, b, k) => a + (b - a) * k;
  let last = performance.now();

  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;

    const k = 1 - Math.exp(-dt * 4.5);
    for (let i = 0; i < 3; i++) {
      params.core[i] = lerp(params.core[i], target.core[i], k);
      params.rim[i] = lerp(params.rim[i], target.rim[i], k);
    }
    params.amp = lerp(params.amp, target.amp, k);
    params.speed = lerp(params.speed, target.speed, k);
    params.noise = lerp(params.noise, target.noise, k);
    params.glow = lerp(params.glow, target.glow, k);

    // быстрая атака, мягкий спад — сфера «дышит» в такт голосу
    const lk = levelTarget > level ? 1 - Math.exp(-dt * 22) : 1 - Math.exp(-dt * 6);
    level = lerp(level, levelTarget, lk);

    resize();
    gl.uniform2f(U.uRes, canvas.width, canvas.height);
    gl.uniform1f(U.uTime, now / 1000);
    gl.uniform1f(U.uLevel, level);
    gl.uniform3fv(U.uCore, params.core);
    gl.uniform3fv(U.uRim, params.rim);
    gl.uniform1f(U.uAmp, params.amp * (1.0 + level * 1.5));
    gl.uniform1f(U.uSpeed, params.speed * (1.0 + level * 0.6));
    gl.uniform1f(U.uNoise, params.noise);
    gl.uniform1f(U.uGlow, params.glow);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // ---------- DOM ----------

  const logEl = document.getElementById("log");
  const dot = document.getElementById("dot");
  const statusText = document.getElementById("statusText");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const muteBtn = document.getElementById("mute");

  const WHO = { user: "вы", assistant: "джарвис", system: "система", error: "ошибка" };

  function addMessage(kind, text) {
    const node = document.createElement("div");
    node.className = `msg ${kind}`;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = WHO[kind] || kind;
    node.append(who, document.createTextNode(text));
    logEl.append(node);
    while (logEl.childElementCount > 60) logEl.firstElementChild.remove();
    logEl.scrollTop = logEl.scrollHeight;
  }

  function applyState(name) {
    if (!PRESETS[name]) return;
    target = PRESETS[name];
    dot.className = `dot ${name}`;
    statusText.textContent = LABEL[name];
  }

  // ---------- websocket ----------

  let socket = null;
  let retry = 500;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws`);

    socket.addEventListener("open", () => {
      retry = 500;
      statusText.textContent = "подключено";
      dot.className = "dot idle";
    });

    socket.addEventListener("message", (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (typeof data.level === "number") levelTarget = data.level;
      if (data.type === "state" || data.type === "level") applyState(data.state);
      if (data.type === "message") addMessage(data.kind, data.text);
    });

    socket.addEventListener("close", () => {
      dot.className = "dot offline";
      statusText.textContent = "нет связи";
      levelTarget = 0;
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 8000);
    });

    socket.addEventListener("error", () => socket.close());
  }
  connect();

  function send(payload) {
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    send({ action: "text", text });
    input.value = "";
  });

  muteBtn.addEventListener("click", () => {
    const muted = muteBtn.getAttribute("aria-pressed") !== "true";
    muteBtn.setAttribute("aria-pressed", String(muted));
    muteBtn.textContent = muted ? "Микрофон выкл." : "Микрофон вкл.";
    send({ action: "mute", value: muted });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement !== input) {
      event.preventDefault();
      input.focus();
    }
  });
})();
