"""Сборка ассетов трёхмерного аватара для интерфейса.

Исходник — FBX из папки модели. На выходе получается компактный GLB и набор
текстур в WebP, которые грузит сцена three.js в `ui3d/`.

Зачем нужен отдельный шаг. Прямой экспорт FBX2glTF даёт 70 МБ: 148 блендшейпов
записываются плотными массивами для всех одиннадцати кусков меша, хотя каждый
шейп трогает лишь несколько сотен вершин лица. Скрипт переводит их в разреженные
аксессоры, выбрасывает нормали блендшейпов и возвращает имена шейпов, которые
FBX2glTF теряет, — без имён морфы бесполезны, по ним и работает мимика.

    python scripts/build_avatar.py
    python scripts/build_avatar.py --source "D:/model/girl.fbx" --force

Конвертер FBX2glTF ставится через npm (`npx fbx2gltf`) и кэшируется в
`.cache/fbx2gltf`. Если его нет и нет сети, скрипт использует ранее собранный GLB.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path.home() / "Desktop" / "lacrimosa-animated-neverness-to-everness"
CHARACTERS = ROOT / "ui3d" / "characters"
REGISTRY = CHARACTERS / "index.json"
CACHE_DIR = ROOT / ".cache" / "fbx2gltf"

# карточка персонажа для меню выбора: имя, голос по умолчанию, акцент интерфейса
DEFAULT_CARD = {
    "lacrimosa": {
        "name": "Лакримоза",
        "subtitle": "Neverness to Everness",
        "voice": "mira",
        "accent": "#7fb2ff",
        "framing": "full",
    },
}

# материал модели → файл текстуры (имена из исходной папки, без учёта регистра)
TEXTURE_MAP: dict[str, str] = {
    "MI_player_004_lacrimosa_01": "T_player_004_lacrimosa_01_d",
    "MI_player_004_lacrimosa_02": "T_player_004_lacrimosa_02_d",
    "MI_player_004_lacrimosa_03": "T_player_004_lacrimosa_01_d",
    "MI_player_004_lacrimosa_hair_01": "T_player_004_lacrimosa_hair_01_d",
    "MI_player_004_lacrimosa_hair_02": "T_player_004_lacrimosa_hair_02_d",
    "MI_player_004_lacrimosa_face": "T_player_004_lacrimosa_face_d",
    "MI_player_004_lacrimosa_eyelash": "T_player_004_lacrimosa_face_d",
    "MI_player_004_lacrimosa_eye": "T_player_004_lacrimosa_eye_d",
    "MI_player_004_lacrimosa_gaoguang": "T_player_004_lacrimosa_eye_d",
    "MI_common_face_mask": "common_face_d",
}

# куски меша, которые в игре служат служебными масками, а в сцене только мешают
HIDDEN_MATERIALS: frozenset[str] = frozenset({"MI_common_face_mask"})

WEBP_QUALITY = 90
MAX_TEXTURE = 2048


# ---------------------------------------------------------------- имена блендшейпов


def blendshape_names(fbx: Path) -> list[str]:
    """Достаёт имена каналов блендшейпов прямо из бинарного FBX.

    FBX2glTF не переносит их в glTF, а без имён 148 морфов — безымянные номера.
    В бинарном FBX канал записан как строка `<имя>\\x00\\x01SubDeformer`, перед
    которой стоит маркер `S` и четырёхбайтовая длина.
    """
    data = fbx.read_bytes()
    marker = b"\x00\x01SubDeformer"
    pattern = re.escape(marker) + rb"S\x11\x00\x00\x00BlendShapeChannel"
    names: list[str] = []
    for match in re.finditer(pattern, data):
        end = match.start()
        name = None
        for back in range(1, 256):
            head = end - back - 4
            if head < 1:
                break
            (length,) = struct.unpack("<I", data[head : head + 4])
            if length == back + len(marker) and data[head - 1 : head] == b"S":
                name = data[head + 4 : end].decode("utf-8", "replace")
                break
        names.append(name or f"shape_{len(names)}")
    return names


# ---------------------------------------------------------------- конвертация FBX


def fbx2gltf_binary() -> Path | None:
    """Путь к FBX2glTF: из кэша, иначе ставим пакет npm во временную папку."""
    cached = CACHE_DIR / "node_modules" / "fbx2gltf" / "bin" / "Windows_NT" / "FBX2glTF.exe"
    if cached.exists():
        return cached
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([npm, "init", "-y"], cwd=CACHE_DIR, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([npm, "install", "fbx2gltf"], cwd=CACHE_DIR, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, OSError):
        return None
    return cached if cached.exists() else None


def convert_fbx(fbx: Path, target: Path) -> Path:
    binary = fbx2gltf_binary()
    if binary is None:
        raise SystemExit("FBX2glTF не найден: нужен npm и доступ в сеть для первой установки")
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(binary),
            "-i", str(fbx),
            "-o", str(target.with_suffix("")),
            "--binary",
            "--pbr-metallic-roughness",
            "--anim-framerate", "bake30",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return target


# ---------------------------------------------------------------- разбор GLB


class Glb:
    """Минимальный читатель и писатель GLB: JSON плюс один буфер."""

    def __init__(self, js: dict[str, Any], blob: bytes) -> None:
        self.js = js
        self.blob = blob

    @classmethod
    def read(cls, path: Path) -> Glb:
        raw = path.read_bytes()
        _, _, _ = struct.unpack("<III", raw[:12])
        offset = 12
        js: dict[str, Any] = {}
        blob = b""
        while offset < len(raw):
            length, kind = struct.unpack("<II", raw[offset : offset + 8])
            chunk = raw[offset + 8 : offset + 8 + length]
            if kind == 0x4E4F534A:
                js = json.loads(chunk.decode("utf-8"))
            else:
                blob = chunk
            offset += 8 + length
        return cls(js, blob)

    def write(self, path: Path) -> None:
        text = json.dumps(self.js, separators=(",", ":")).encode("utf-8")
        text += b" " * (-len(text) % 4)
        blob = self.blob + b"\x00" * (-len(self.blob) % 4)
        total = 12 + 8 + len(text) + 8 + len(blob)
        with path.open("wb") as handle:
            handle.write(struct.pack("<III", 0x46546C67, 2, total))
            handle.write(struct.pack("<II", len(text), 0x4E4F534A))
            handle.write(text)
            handle.write(struct.pack("<II", len(blob), 0x004E4942))
            handle.write(blob)

    # --- чтение аксессоров ---

    _COMPONENTS = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
    _COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def read_accessor(self, index: int) -> np.ndarray:
        acc = self.js["accessors"][index]
        width = self._COUNTS[acc["type"]]
        dtype = np.dtype("<" + self._COMPONENTS[acc["componentType"]])
        count = acc["count"]
        out = np.zeros((count, width), dtype=dtype)
        if "bufferView" in acc:
            view = self.js["bufferViews"][acc["bufferView"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = view.get("byteStride") or width * dtype.itemsize
            raw = np.frombuffer(self.blob, dtype=np.uint8, count=stride * count, offset=start)
            rows = raw.reshape(count, stride)[:, : width * dtype.itemsize]
            out = np.ascontiguousarray(rows).view(dtype).reshape(count, width)
        return out


# ---------------------------------------------------------------- сжатие морфов


def compact_morphs(glb: Glb, names: list[str], epsilon_scale: float = 5e-5) -> dict[str, Any]:
    """Переводит плотные блендшейпы в разреженные и выбрасывает пустые.

    Пустые морфы нельзя просто удалить — glTF требует одинакового набора целей у
    всех примитивов меша. Поэтому все нулевые цели одного размера ссылаются на
    один общий разреженный аксессор: место занимает не 63 МБ, а несколько байт.
    """
    mesh = glb.js["meshes"][0]
    accessors = glb.js["accessors"]

    # цена ошибки — дрожание лица, поэтому порог считаем от габарита модели
    positions = [glb.read_accessor(p["attributes"]["POSITION"]) for p in mesh["primitives"]]
    extent = float(max(np.ptp(np.concatenate(positions), axis=0)))
    epsilon = extent * epsilon_scale

    payload = bytearray()
    views: list[dict[str, Any]] = []

    def add_view(data: np.ndarray) -> int:
        """Возвращает отрицательный номер — метку «это новый вид».

        Настоящие номера станут известны только после перепаковки буфера, а
        ссылки на них надо расставить уже сейчас. Отрицательные значения нельзя
        спутать со старыми номерами, поэтому перепаковка их узнаёт и заменяет.
        """
        payload.extend(b"\x00" * (-len(payload) % 4))
        offset = len(payload)
        raw = np.ascontiguousarray(data).tobytes()
        payload.extend(raw)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        return -len(views)

    zero_cache: dict[int, int] = {}

    def zero_accessor(count: int) -> int:
        """Цель без смещений: одна ненулевая запись со значением ноль."""
        if count in zero_cache:
            return zero_cache[count]
        indices = add_view(np.zeros(1, dtype="<u4"))
        values = add_view(np.zeros((1, 3), dtype="<f4"))
        accessors.append({
            "type": "VEC3", "componentType": 5126, "count": count,
            "min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0],
            "sparse": {
                "count": 1,
                "indices": {"bufferView": indices, "byteOffset": 0, "componentType": 5125},
                "values": {"bufferView": values, "byteOffset": 0},
            },
        })
        zero_cache[count] = len(accessors) - 1
        return zero_cache[count]

    live = np.zeros(len(names), dtype=bool)
    for primitive, base in zip(mesh["primitives"], positions):
        count = base.shape[0]
        targets = primitive.get("targets") or []
        rebuilt: list[dict[str, int]] = []
        for order, target in enumerate(targets):
            if "POSITION" not in target:
                rebuilt.append({"POSITION": zero_accessor(count)})
                continue
            delta = glb.read_accessor(target["POSITION"]).astype(np.float32)
            moved = np.flatnonzero(np.abs(delta).max(axis=1) > epsilon).astype(np.uint32)
            if moved.size == 0:
                rebuilt.append({"POSITION": zero_accessor(count)})
                continue
            live[order] = True
            picked = np.ascontiguousarray(delta[moved], dtype="<f4")
            indices = add_view(np.ascontiguousarray(moved, dtype="<u4"))
            values = add_view(picked)
            accessors.append({
                "type": "VEC3", "componentType": 5126, "count": count,
                # границы считаются по всему аксессору, а нули в нём остались
                "min": np.minimum(picked.min(axis=0), 0.0).tolist(),
                "max": np.maximum(picked.max(axis=0), 0.0).tolist(),
                "sparse": {
                    "count": int(moved.size),
                    "indices": {"bufferView": indices, "byteOffset": 0, "componentType": 5125},
                    "values": {"bufferView": values, "byteOffset": 0},
                },
            })
            rebuilt.append({"POSITION": len(accessors) - 1})
        primitive["targets"] = rebuilt

    _drop_unused_accessors(glb)
    _rebase(glb, views, bytes(payload))
    mesh.setdefault("extras", {})["targetNames"] = names
    return {
        "epsilon": epsilon,
        "active": [name for name, flag in zip(names, live) if flag],
        "empty": [name for name, flag in zip(names, live) if not flag],
    }


_ACCESSOR_KEYS = ("POSITION", "NORMAL", "TANGENT", "COLOR_0", "JOINTS_0", "WEIGHTS_0",
                  "TEXCOORD_0", "TEXCOORD_1", "indices", "inverseBindMatrices", "input", "output")


def _drop_unused_accessors(glb: Glb) -> None:
    """Убирает плотные аксессуры старых морфов: иначе перепаковка тянет их данные."""
    used: list[int] = []
    seen: set[int] = set()

    def visit(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                visit(value, name)
        elif isinstance(node, list):
            for item in node:
                visit(item, key)
        elif isinstance(node, int) and key in _ACCESSOR_KEYS and not isinstance(node, bool):
            if node not in seen:
                seen.add(node)
                used.append(node)

    for section in ("meshes", "skins", "animations"):
        visit(glb.js.get(section, []))

    order = sorted(seen)
    remap = {old: new for new, old in enumerate(order)}
    glb.js["accessors"] = [glb.js["accessors"][old] for old in order]

    def relink(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            for name, value in list(node.items()):
                if name in _ACCESSOR_KEYS and isinstance(value, int) and not isinstance(value, bool):
                    node[name] = remap[value]
                else:
                    relink(value, name)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                if key in _ACCESSOR_KEYS and isinstance(item, int) and not isinstance(item, bool):
                    node[index] = remap[item]
                else:
                    relink(item, key)

    for section in ("meshes", "skins", "animations"):
        relink(glb.js.get(section, []))


def _rebase(glb: Glb, extra_views: list[dict[str, Any]], payload: bytes) -> None:
    """Переносит буфер: сначала всё старое, что ещё используется, затем новые данные."""
    used: set[int] = set()

    def mark(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "bufferView" and isinstance(value, int):
                    if value >= 0:  # отрицательные — новые виды, их ещё нет в старом буфере
                        used.add(value)
                else:
                    mark(value)
        elif isinstance(node, list):
            for item in node:
                mark(item)

    mark({k: v for k, v in glb.js.items() if k != "bufferViews"})

    old_views = glb.js["bufferViews"]
    out = bytearray()
    remap: dict[int, int] = {}
    kept: list[dict[str, Any]] = []
    for index in sorted(used):
        view = old_views[index]
        start = view.get("byteOffset", 0)
        raw = glb.blob[start : start + view["byteLength"]]
        out.extend(b"\x00" * (-len(out) % 4))
        fresh = {"buffer": 0, "byteOffset": len(out), "byteLength": len(raw)}
        if "byteStride" in view:
            fresh["byteStride"] = view["byteStride"]
        if "target" in view:
            fresh["target"] = view["target"]
        out.extend(raw)
        remap[index] = len(kept)
        kept.append(fresh)

    out.extend(b"\x00" * (-len(out) % 4))
    base = len(out)
    out.extend(payload)
    first_new = len(kept)
    for view in extra_views:
        view["byteOffset"] += base
        kept.append(view)

    def relink(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "bufferView" and isinstance(value, int):
                    node[key] = first_new + (-value - 1) if value < 0 else remap.get(value, value)
                else:
                    relink(value)
        elif isinstance(node, list):
            for item in node:
                relink(item)

    relink({k: v for k, v in glb.js.items() if k != "bufferViews"})
    glb.js["bufferViews"] = kept
    glb.blob = bytes(out)
    glb.js["buffers"] = [{"byteLength": len(out)}]


def strip_textures(glb: Glb) -> None:
    """Выбрасывает пустые ссылки на текстуры: материалы собираются в сцене."""
    for material in glb.js.get("materials", []):
        material.pop("occlusionTexture", None)
        material.pop("emissiveTexture", None)
        material.pop("normalTexture", None)
        pbr = material.get("pbrMetallicRoughness")
        if pbr:
            pbr.pop("baseColorTexture", None)
            pbr.pop("metallicRoughnessTexture", None)
    glb.js.pop("textures", None)
    glb.js.pop("images", None)
    glb.js.pop("samplers", None)


# ---------------------------------------------------------------- текстуры


def convert_textures(source: Path, target: Path) -> dict[str, str]:
    from PIL import Image

    target.mkdir(parents=True, exist_ok=True)
    files = {path.stem.lower(): path for path in source.glob("*") if path.suffix.lower() in
             (".png", ".jpg", ".jpeg", ".tga", ".webp")}
    written: dict[str, str] = {}
    for material, stem in TEXTURE_MAP.items():
        path = files.get(stem.lower())
        if path is None:
            print(f"  текстуры нет: {stem} (материал {material})")
            continue
        name = f"{stem}.webp"
        out = target / name
        if not out.exists():
            with Image.open(path) as image:
                image = image.convert("RGBA")
                if max(image.size) > MAX_TEXTURE:
                    ratio = MAX_TEXTURE / max(image.size)
                    image = image.resize(
                        (int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS
                    )
                image.save(out, "WEBP", quality=WEBP_QUALITY, method=5)
        written[material] = name
    return written


# ---------------------------------------------------------------- сборка


def find_fbx(source: Path) -> Path:
    if source.is_file():
        return source
    candidates = sorted(source.rglob("*.fbx"), key=lambda p: p.stat().st_size, reverse=True)
    if not candidates:
        raise SystemExit(f"FBX не найден в {source}")
    return candidates[0]


def find_textures(source: Path) -> Path:
    if source.is_file():
        source = source.parent.parent
    for name in ("textures", "Textures", "texture"):
        candidate = source / name
        if candidate.is_dir():
            return candidate
    return source


def humanize(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} МБ"


def update_registry(character: str, card: dict[str, Any]) -> None:
    """Список персонажей для меню выбора. Новая папка — новый пункт в меню."""
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"characters": []}
    if REGISTRY.exists():
        try:
            data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    items = [item for item in data.get("characters", []) if item.get("id") != character]
    items.append({"id": character, **card})
    items.sort(key=lambda item: item["id"])
    REGISTRY.write_text(
        json.dumps({"characters": items}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сборка ассетов 3D-аватара")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="папка или файл FBX")
    parser.add_argument("--id", default=None, help="ключ персонажа (по умолчанию — имя папки)")
    parser.add_argument("--name", default=None, help="как персонаж называется в меню")
    parser.add_argument("--voice", default=None, help="голос по умолчанию")
    parser.add_argument("--out", type=Path, default=None, help="куда положить ассеты")
    parser.add_argument("--force", action="store_true", help="пересобрать, даже если файлы есть")
    args = parser.parse_args(list(argv) if argv is not None else None)

    fbx = find_fbx(args.source)
    textures = find_textures(args.source)

    character = args.id or _character_id(args.source, fbx)
    args.out = args.out or (CHARACTERS / character)
    args.out.mkdir(parents=True, exist_ok=True)
    final = args.out / "avatar.glb"

    if final.exists() and not args.force:
        print(f"уже собрано: {final} ({humanize(final.stat().st_size)}); --force чтобы пересобрать")
        return 0

    raw = CACHE_DIR / "raw" / f"{fbx.stem}.glb"
    if not raw.exists() or args.force:
        print(f"конвертирую {fbx.name}…")
        convert_fbx(fbx, raw)
    print(f"сырой GLB: {humanize(raw.stat().st_size)}")

    names = blendshape_names(fbx)
    print(f"блендшейпов в FBX: {len(names)}")

    glb = Glb.read(raw)
    mesh = glb.js["meshes"][0]
    targets = len(mesh["primitives"][0].get("targets") or [])
    if targets != len(names):
        print(f"  внимание: {targets} морфов в GLB против {len(names)} имён в FBX")
        names = (names + [f"shape_{i}" for i in range(targets)])[:targets]

    strip_textures(glb)  # до перепаковки: иначе встроенная картинка уедет в новый буфер
    report = compact_morphs(glb, names)

    materials = [m.get("name", "") for m in glb.js.get("materials", [])]
    written = convert_textures(textures, args.out / "textures")

    glb.write(final)
    print(f"итог: {final} ({humanize(final.stat().st_size)})")
    print(f"живых морфов: {len(report['active'])} из {len(names)}")

    manifest = {
        "id": character,
        "model": final.name,
        "textures": written,
        "hidden": sorted(HIDDEN_MATERIALS),
        "materials": materials,
        "morphs": names,
        "activeMorphs": report["active"],
    }
    (args.out / "avatar.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    card = dict(DEFAULT_CARD.get(character, {}))
    card.setdefault("name", args.name or character.capitalize())
    card.setdefault("subtitle", "")
    card.setdefault("voice", args.voice or "mira")
    card.setdefault("accent", "#7fb2ff")
    card.setdefault("framing", "full")
    if args.name:
        card["name"] = args.name
    if args.voice:
        card["voice"] = args.voice
    update_registry(character, card)

    print(f"манифест: {args.out / 'avatar.json'}")
    print(f"персонаж «{card['name']}» записан в {REGISTRY}")
    return 0


def _character_id(source: Path, fbx: Path) -> str:
    stem = (source if source.is_dir() else fbx).stem if source.is_file() else source.name
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    # имена вроде «lacrimosa-animated-neverness-to-everness» режем до первого слова
    return slug.split("-")[0] or "character"


if __name__ == "__main__":
    sys.exit(main())
