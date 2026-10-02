// Point clouds the particle swarm morphs between. Every shape fills the same N slots, and
// each slot is placed independently, so a morph reads as the swarm tearing apart and
// re-assembling rather than as one surface sliding into another.

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gauss(rand) {
  const u = Math.max(rand(), 1e-9);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

function randomDir(rand) {
  const z = rand() * 2 - 1;
  const a = rand() * Math.PI * 2;
  const r = Math.sqrt(1 - z * z);
  return [r * Math.cos(a), r * Math.sin(a), z];
}

/** 0 — the voice core: a luminous shell, a hot inner core and a thin halo of dust. */
function sphere(out, n, rand) {
  const R = 2.25;
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const k = rand();
    let x, y, z;
    if (k < 0.72) {
      const yy = 1 - (i / (n - 1)) * 2;
      const r = Math.sqrt(1 - yy * yy);
      const th = golden * i;
      const j = 1 + gauss(rand) * 0.012;
      x = Math.cos(th) * r * R * j;
      y = yy * R * j;
      z = Math.sin(th) * r * R * j;
    } else if (k < 0.86) {
      const [dx, dy, dz] = randomDir(rand);
      const r = Math.pow(rand(), 0.6) * 0.85;
      x = dx * r; y = dy * r; z = dz * r;
    } else {
      const [dx, dy, dz] = randomDir(rand);
      const r = R * (1.08 + Math.pow(rand(), 2.2) * 0.55);
      x = dx * r; y = dy * r; z = dz * r;
    }
    out[i * 3] = x; out[i * 3 + 1] = y; out[i * 3 + 2] = z;
  }
}

/** 1 — hearing: a stack of speech waveforms receding in depth. */
function wave(out, n, rand) {
  const LINES = 26;
  for (let i = 0; i < n; i++) {
    const j = Math.floor(rand() * LINES);
    const phase = j * 0.37;
    const x = (rand() * 2 - 1) * 6.2;
    const env = 1.35 * Math.exp(-(x * x) / 9) * (0.45 + 0.55 * Math.abs(Math.sin(x * 0.9 + j * 0.21)));
    const y = env * (Math.sin(x * 2.3 + phase) * 0.72 + Math.sin(x * 6.1 + phase * 2.3) * 0.28);
    const z = (j / (LINES - 1) - 0.5) * 2.2;
    out[i * 3] = x + gauss(rand) * 0.01;
    out[i * 3 + 1] = y + gauss(rand) * 0.018;
    out[i * 3 + 2] = z + gauss(rand) * 0.012;
  }
}

/** 2 — thinking: a two-lobed graph of nodes and the synapses between them. */
function neural(out, n, rand) {
  const NODES = 84;
  const nodes = [];
  while (nodes.length < NODES) {
    const x = (rand() * 2 - 1) * 2.7;
    const y = (rand() * 2 - 1) * 1.8;
    const z = (rand() * 2 - 1) * 1.9;
    const e = (x * x) / 7.3 + (y * y) / 3.24 + (z * z) / 3.6;
    if (e > 1 || Math.abs(x) < 0.16) continue;
    nodes.push([x, y, z]);
  }
  const edges = [];
  nodes.forEach((a, ia) => {
    const near = nodes
      .map((b, ib) => [ib, (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2])
      .filter(([ib]) => ib !== ia)
      .sort((p, q) => p[1] - q[1])
      .slice(0, 3);
    near.forEach(([ib]) => { if (ia < ib || !edges.some(([p, q]) => p === ib && q === ia)) edges.push([ia, ib]); });
  });
  for (let i = 0; i < n; i++) {
    let x, y, z;
    if (rand() < 0.3) {
      const c = nodes[Math.floor(rand() * NODES)];
      const s = 0.07 + rand() * 0.05;
      x = c[0] + gauss(rand) * s; y = c[1] + gauss(rand) * s; z = c[2] + gauss(rand) * s;
    } else {
      const [ia, ib] = edges[Math.floor(rand() * edges.length)];
      const a = nodes[ia]; const b = nodes[ib];
      const t = rand();
      const sag = Math.sin(t * Math.PI) * 0.12;
      x = a[0] + (b[0] - a[0]) * t + gauss(rand) * 0.012;
      y = a[1] + (b[1] - a[1]) * t - sag + gauss(rand) * 0.012;
      z = a[2] + (b[2] - a[2]) * t + gauss(rand) * 0.012;
    }
    out[i * 3] = x; out[i * 3 + 1] = y; out[i * 3 + 2] = z;
  }
}

/** 3 — acting: 88 wireframe cubes, one per tool, on a gently curved wall. */
function tools(out, n, rand) {
  const COLS = 11; const ROWS = 8; const GAP = 0.6; const S = 0.36;
  const corners = [
    [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
    [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
  ];
  const cubeEdges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
  for (let i = 0; i < n; i++) {
    const cell = i % (COLS * ROWS);
    const cx = ((cell % COLS) - (COLS - 1) / 2) * GAP;
    const cy = (Math.floor(cell / COLS) - (ROWS - 1) / 2) * GAP;
    const cz = -cx * cx * 0.07;
    const h = S / 2;
    let x, y, z;
    if (rand() < 0.8) {
      const [a, b] = cubeEdges[Math.floor(rand() * 12)];
      const t = rand();
      const A = corners[a]; const B = corners[b];
      x = (A[0] + (B[0] - A[0]) * t) * h;
      y = (A[1] + (B[1] - A[1]) * t) * h;
      z = (A[2] + (B[2] - A[2]) * t) * h;
    } else {
      const face = Math.floor(rand() * 3);
      const sign = rand() < 0.5 ? -1 : 1;
      const u = (rand() * 2 - 1) * h; const v = (rand() * 2 - 1) * h;
      [x, y, z] = face === 0 ? [sign * h, u, v] : face === 1 ? [u, sign * h, v] : [u, v, sign * h];
    }
    out[i * 3] = cx + x; out[i * 3 + 1] = cy + y; out[i * 3 + 2] = cz + z;
  }
}

function capsulePoint(rand, a, b, r) {
  const t = rand();
  const [dx, dy, dz] = randomDir(rand);
  const rr = r * Math.sqrt(rand());
  return [
    a[0] + (b[0] - a[0]) * t + dx * rr,
    a[1] + (b[1] - a[1]) * t + dy * rr,
    a[2] + (b[2] - a[2]) * t + dz * rr * 0.55,
  ];
}

/** 4 — the mark: the Y from Yuki's icon inside its halo ring. */
function logo(out, n, rand) {
  const J = [0, 0.05, 0];
  const strokes = [
    [[-1.0, 1.12, 0], J, 1.0],
    [[1.0, 1.12, 0], J, 1.0],
    [J, [0, -1.3, 0], 1.0],
  ];
  const RING = 2.45;
  for (let i = 0; i < n; i++) {
    let p;
    if (rand() < 0.62) {
      const [a, b] = strokes[Math.floor(rand() * 3)];
      p = capsulePoint(rand, a, b, 0.2);
    } else {
      const ang = rand() * Math.PI * 2;
      const tube = rand() < 0.8 ? 0.05 : 0.22;
      const [dx, dy, dz] = randomDir(rand);
      const r = RING + dx * tube * rand();
      p = [Math.cos(ang) * r, Math.sin(ang) * r, dz * tube * 0.6 + dy * 0.01];
    }
    out[i * 3] = p[0]; out[i * 3 + 1] = p[1]; out[i * 3 + 2] = p[2];
  }
}

export const SHAPE_COUNT = 5;

export function buildShapes(n) {
  const builders = [sphere, wave, neural, tools, logo];
  const shapes = builders.map((build, k) => {
    const arr = new Float32Array(n * 3);
    build(arr, n, mulberry32(1337 + k * 7919));
    return arr;
  });
  const rand = mulberry32(42);
  const rnd = new Float32Array(n * 4);
  for (let i = 0; i < rnd.length; i++) rnd[i] = rand();
  return { shapes, rnd };
}

/** Three telemetry rings like the ones behind Yuki's avatar: solid, dashed and ticked. */
export function buildRings(rand = mulberry32(7)) {
  const pts = [];
  const meta = [];
  const push = (x, y, z, ring) => { pts.push(x, y, z); meta.push(ring, rand()); };
  for (let i = 0; i < 1800; i++) {
    const a = (i / 1800) * Math.PI * 2;
    push(Math.cos(a) * 3.05, Math.sin(a) * 3.05, 0, 0);
  }
  for (let i = 0; i < 2400; i++) {
    const a = (i / 2400) * Math.PI * 2;
    const seg = (a / (Math.PI * 2)) * 36;
    if (seg % 1 > 0.62) continue;
    push(Math.cos(a) * 3.5, Math.sin(a) * 3.5, 0, 1);
  }
  for (let t = 0; t < 120; t++) {
    const a = (t / 120) * Math.PI * 2;
    const len = t % 10 === 0 ? 0.26 : 0.1;
    for (let k = 0; k < 10; k++) {
      const r = 3.95 + (k / 9) * len;
      push(Math.cos(a) * r, Math.sin(a) * r, 0, 2);
    }
  }
  return { positions: new Float32Array(pts), meta: new Float32Array(meta) };
}

export function buildStars(count, rand = mulberry32(99)) {
  const arr = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const [dx, dy, dz] = randomDir(rand);
    const r = 14 + rand() * 26;
    arr[i * 3] = dx * r; arr[i * 3 + 1] = dy * r; arr[i * 3 + 2] = dz * r - 8;
  }
  return arr;
}
