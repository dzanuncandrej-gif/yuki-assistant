"""Подготовка GLB к вебу: текстуры ужимаются, лишняя геометрия выбрасывается.

Модель самурая весит восемьдесят мегабайт, и почти всё это — текстуры PNG в
четыре тысячи точек. Геометрии в ней всего сорок пять тысяч треугольников, то
есть она лёгкая; тяжёлыми её делают картинки. Восемьдесят мегабайт в браузере —
это полминуты ожидания на телефоне, и половина посетителей уходит раньше.

Что делает скрипт:

* переводит текстуры в WebP и уменьшает до разумного размера. Карта нормалей и
  цвет остаются крупными, шероховатость и металличность — вдвое меньше: на них
  мелких деталей не видно, а весят они столько же;
* выбрасывает пол. В модели лежит плита с тремя текстурами на семнадцать
  мегабайт ради ста четырнадцати треугольников — на сайте персонаж стоит на
  своей сцене, и пол из модели не нужен;
* пересобирает двоичный буфер, пересчитывая смещения.

    python scripts/optimize_glb.py --source samurai.glb --out web/page/assets/samurai.glb
"""

from __future__ import annotations

import argparse
import io
import json
import struct
import sys
from pathlib import Path
from typing import Any

MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

# Предельный размер стороны текстуры по назначению. Цвет и нормали несут форму и
# рисунок, их режем меньше; шероховатость и металличность — почти плоские карты.
LIMITS = {"base": 2048, "normal": 2048, "other": 1024}


def read_glb(path: Path) -> tuple[dict[str, Any], bytearray]:
    raw = path.read_bytes()
    magic, _version, _total = struct.unpack_from("<III", raw, 0)
    if magic != MAGIC:
        raise SystemExit(f"{path} — не GLB")
    offset, meta, binary = 12, None, bytearray()
    while offset < len(raw):
        length, kind = struct.unpack_from("<II", raw, offset)
        body = raw[offset + 8 : offset + 8 + length]
        if kind == CHUNK_JSON:
            meta = json.loads(body)
        elif kind == CHUNK_BIN:
            binary = bytearray(body)
        offset += 8 + length + (-length % 4)
    if meta is None:
        raise SystemExit("в GLB нет JSON-чанка")
    return meta, binary


def write_glb(path: Path, meta: dict[str, Any], binary: bytes) -> None:
    text = json.dumps(meta, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (-len(text) % 4)
    body = bytes(binary) + b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(struct.pack("<III", MAGIC, 2, total))
        handle.write(struct.pack("<II", len(text), CHUNK_JSON))
        handle.write(text)
        handle.write(struct.pack("<II", len(body), CHUNK_BIN))
        handle.write(body)


def texture_roles(meta: dict[str, Any]) -> dict[int, str]:
    """Для каждой картинки — зачем она нужна. От этого зависит, как сильно жать."""
    roles: dict[int, str] = {}

    def mark(texture_index: Any, role: str) -> None:
        if not isinstance(texture_index, int):
            return
        texture = meta["textures"][texture_index]
        source = texture.get("source")
        if isinstance(source, int):
            roles.setdefault(source, role)

    for material in meta.get("materials", []):
        pbr = material.get("pbrMetallicRoughness", {})
        mark((pbr.get("baseColorTexture") or {}).get("index"), "base")
        mark((pbr.get("metallicRoughnessTexture") or {}).get("index"), "other")
        mark((material.get("normalTexture") or {}).get("index"), "normal")
        mark((material.get("occlusionTexture") or {}).get("index"), "other")
        mark((material.get("emissiveTexture") or {}).get("index"), "base")
    return roles


def drop_meshes(meta: dict[str, Any], names: tuple[str, ...]) -> set[int]:
    """Убирает примитивы с указанными материалами. Возвращает осиротевшие картинки."""
    if not names:
        return set()
    doomed = {
        index for index, material in enumerate(meta.get("materials", []))
        if any(mark.lower() in str(material.get("name", "")).lower() for mark in names)
    }
    if not doomed:
        return set()

    for mesh in meta.get("meshes", []):
        mesh["primitives"] = [
            primitive for primitive in mesh.get("primitives", [])
            if primitive.get("material") not in doomed
        ]

    # какие картинки больше никем не используются
    used: set[int] = set()
    for index, material in enumerate(meta.get("materials", [])):
        if index in doomed:
            continue
        for texture_index in _material_textures(material):
            source = meta["textures"][texture_index].get("source")
            if isinstance(source, int):
                used.add(source)
    orphans = {
        meta["textures"][t].get("source")
        for index in doomed
        for t in _material_textures(meta["materials"][index])
    }
    return {item for item in orphans if isinstance(item, int) and item not in used}


def _material_textures(material: dict[str, Any]) -> list[int]:
    pbr = material.get("pbrMetallicRoughness", {})
    found = [
        (pbr.get("baseColorTexture") or {}).get("index"),
        (pbr.get("metallicRoughnessTexture") or {}).get("index"),
        (material.get("normalTexture") or {}).get("index"),
        (material.get("occlusionTexture") or {}).get("index"),
        (material.get("emissiveTexture") or {}).get("index"),
    ]
    return [item for item in found if isinstance(item, int)]


def rebuild(meta: dict[str, Any], binary: bytearray, drop: tuple[str, ...],
            quality: int) -> tuple[dict[str, Any], bytes, list[str]]:
    from PIL import Image

    orphans = drop_meshes(meta, drop)
    roles = texture_roles(meta)
    views = meta.get("bufferViews", [])
    notes: list[str] = []

    # что лежит в каждом bufferView сейчас
    chunks: list[bytes] = []
    for view in views:
        start = int(view.get("byteOffset", 0))
        chunks.append(bytes(binary[start : start + int(view["byteLength"])]))

    for index, image in enumerate(meta.get("images", [])):
        view_index = image.get("bufferView")
        if not isinstance(view_index, int):
            continue
        before = len(chunks[view_index])

        if index in orphans:
            # текстура ушедшей геометрии: оставляем точку, чтобы не сбивать нумерацию
            tiny = Image.new("RGB", (4, 4), (16, 18, 24))
            buffer = io.BytesIO()
            tiny.save(buffer, "WEBP", quality=60)
            chunks[view_index] = buffer.getvalue()
            image["mimeType"] = "image/webp"
            notes.append(f"  выброшено: картинка {index} {before/1048576:.1f} МБ → 0")
            continue

        try:
            picture = Image.open(io.BytesIO(chunks[view_index]))
            picture.load()
        except Exception as err:  # noqa: BLE001 — не картинка, оставляем как есть
            notes.append(f"  пропуск картинки {index}: {str(err)[:60]}")
            continue

        limit = LIMITS.get(roles.get(index, "other"), LIMITS["other"])
        if max(picture.size) > limit:
            picture.thumbnail((limit, limit), Image.LANCZOS)
        has_alpha = picture.mode in ("RGBA", "LA") or "transparency" in picture.info
        picture = picture.convert("RGBA" if has_alpha else "RGB")

        buffer = io.BytesIO()
        picture.save(buffer, "WEBP", quality=quality, method=6)
        chunks[view_index] = buffer.getvalue()
        image["mimeType"] = "image/webp"
        notes.append(
            f"  {roles.get(index, 'other'):6} {before/1048576:6.2f} → "
            f"{len(chunks[view_index])/1048576:5.2f} МБ  {picture.size[0]}px"
        )

    # заново складываем буфер, выравнивая каждый кусок по четыре байта
    packed = bytearray()
    for view_index, view in enumerate(views):
        packed += b"\x00" * (-len(packed) % 4)
        view["byteOffset"] = len(packed)
        view["byteLength"] = len(chunks[view_index])
        packed += chunks[view_index]

    meta["buffers"] = [{"byteLength": len(packed)}]
    meta.setdefault("extensionsUsed", [])
    if "EXT_texture_webp" not in meta["extensionsUsed"]:
        meta["extensionsUsed"].append("EXT_texture_webp")
    return meta, bytes(packed), notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Ужимает GLB для веба")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--drop", default="floor", help="материалы на выброс, через запятую")
    parser.add_argument("--quality", type=int, default=88)
    args = parser.parse_args()

    meta, binary = read_glb(args.source)
    before = args.source.stat().st_size
    drop = tuple(item.strip() for item in args.drop.split(",") if item.strip())
    meta, packed, notes = rebuild(meta, binary, drop, args.quality)
    write_glb(args.out, meta, packed)
    after = args.out.stat().st_size

    print("\n".join(notes))
    print(f"\n{before/1048576:.1f} МБ → {after/1048576:.1f} МБ "
          f"(в {before/max(after,1):.1f} раза меньше)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
