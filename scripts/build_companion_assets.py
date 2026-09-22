"""Нарезка листа персонажа на слои для живой анимации.

На вход — оригинальный лист (assets/companion/reference.png). На выход — слои с
прозрачным фоном и разметка в JSON. Рисунок не перерисовывается: скрипт только
вырезает области исходного изображения, поэтому персонаж на экране остаётся тем
же самым, что на референсе.

    python scripts/build_companion_assets.py            # собрать слои
    python scripts/build_companion_assets.py --preview  # плюс контрольный кадр

Слои:
    figure.png      фигура целиком (фронтальная поза), фон удалён
    head.png        голова с ушами и чёлкой, нижний край растушёван
    hair_left.png   боковая прядь слева (качается отдельно)
    hair_right.png  боковая прядь справа
    parts.json      координаты глаз, рта, шеи и прочих опорных точек
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "companion" / "reference.png"
TARGET = ROOT / "assets" / "companion" / "parts"

# Разметка листа 1536×1024. Координаты выверены по оригиналу: фронтальная фигура
# слева, ряд голов с эмоциями снизу.
FIGURE_BOX = (14, 10, 310, 686)    # ниже 686 начинается следующий ряд листа
UPSCALE = 2                        # рисуем крупнее исходника: на экране меньше мыла

# Всё, что ниже, — в координатах вырезанной фигуры (до масштабирования).
HEAD_BOX = (84, 0, 232, 200)       # голова с ушами, хвостом чёлки и верхом волос
NECK_PIVOT = (150, 152)            # вокруг этой точки голова поворачивается
EYE_LEFT = (126, 98, 148, 120)     # прямоугольники глаз
EYE_RIGHT = (158, 97, 180, 119)
MOUTH_BOX = (140, 124, 162, 140)
BROW_BAND = (120, 88, 186, 100)
HAIR_LEFT_BOX = (86, 60, 128, 330)
HAIR_RIGHT_BOX = (188, 60, 232, 330)
TORSO_TOP = 160
HIP_Y = 330
FLOOR_Y = 672


def _background_mask(rgb: np.ndarray, tolerance: int = 26) -> np.ndarray:
    """Заливка от краёв: фон — только то, что связано с рамкой кадра.

    Порог по цвету оставил бы дыры в светлых волосах, поэтому идём волной от
    границы и не заходим внутрь силуэта.
    """
    height, width, _ = rgb.shape
    background = np.median(
        np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]), axis=0
    )
    close = np.abs(rgb.astype(np.int16) - background).sum(axis=2) < tolerance

    visited = np.zeros((height, width), dtype=bool)
    stack: list[tuple[int, int]] = []
    for x in range(width):
        stack.append((0, x))
        stack.append((height - 1, x))
    for y in range(height):
        stack.append((y, 0))
        stack.append((y, width - 1))

    while stack:
        y, x = stack.pop()
        if y < 0 or y >= height or x < 0 or x >= width:
            continue
        if visited[y, x] or not close[y, x]:
            continue
        visited[y, x] = True
        stack.append((y + 1, x))
        stack.append((y - 1, x))
        stack.append((y, x + 1))
        stack.append((y, x - 1))
    return visited


def _cut_figure(sheet: Image.Image) -> Image.Image:
    figure = sheet.crop(FIGURE_BOX).convert("RGB")
    rgb = np.asarray(figure)
    background = _background_mask(rgb)

    alpha = np.where(background, 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    image = Image.fromarray(rgba, mode="RGBA")

    # мягкий край: полупрозрачная кайма прячет «пилу» после заливки
    from PIL import ImageFilter

    smooth = image.split()[3].filter(ImageFilter.GaussianBlur(0.8))
    image.putalpha(smooth)
    return image


def _feather_bottom(image: Image.Image, height: int) -> Image.Image:
    """Растворяет нижний край слоя — стык головы с телом становится незаметным."""
    alpha = np.asarray(image.split()[3]).astype(np.float32)
    rows = alpha.shape[0]
    ramp = np.ones(rows, dtype=np.float32)
    band = min(height, rows)
    ramp[rows - band:] = np.linspace(1.0, 0.0, band)
    faded = (alpha * ramp[:, None]).astype(np.uint8)
    result = image.copy()
    result.putalpha(Image.fromarray(faded, mode="L"))
    return result


def _feather_edge(image: Image.Image, width: int, side: str) -> Image.Image:
    """Растушёвка боковой кромки пряди."""
    alpha = np.asarray(image.split()[3]).astype(np.float32)
    columns = alpha.shape[1]
    ramp = np.ones(columns, dtype=np.float32)
    band = min(width, columns)
    if side == "left":
        ramp[:band] = np.linspace(0.0, 1.0, band)
    else:
        ramp[columns - band:] = np.linspace(1.0, 0.0, band)
    faded = (alpha * ramp[None, :]).astype(np.uint8)
    result = image.copy()
    result.putalpha(Image.fromarray(faded, mode="L"))
    return result


def _scale(box: tuple[int, int, int, int]) -> list[int]:
    return [value * UPSCALE for value in box]


def build(source: Path = SOURCE, target: Path = TARGET) -> dict[str, Any]:
    if not source.exists():
        raise SystemExit(f"нет исходного листа: {source}")
    target.mkdir(parents=True, exist_ok=True)

    sheet = Image.open(source).convert("RGB")
    figure = _cut_figure(sheet)
    figure = figure.resize((figure.width * UPSCALE, figure.height * UPSCALE), Image.LANCZOS)
    figure.save(target / "figure.png")

    head = figure.crop(_scale(HEAD_BOX))
    head = _feather_bottom(head, 26 * UPSCALE)
    head.save(target / "head.png")

    # тело без головы: голова живёт отдельным слоем и поворачивается, поэтому из
    # общей фигуры её нужно убрать — иначе из-под слоя выглядывает неподвижная
    body = figure.copy()
    box = _scale(HEAD_BOX)
    hole = Image.new("L", body.size, 255)
    from PIL import ImageDraw
    from PIL import ImageFilter as _Filter

    width = box[2] - box[0]
    height = box[3] - box[1]
    ImageDraw.Draw(hole).ellipse(
        [box[0] + width * 0.10, box[1] + height * 0.05,
         box[0] + width * 0.90, box[1] + height * 0.92],
        fill=0,
    )
    hole = hole.filter(_Filter.GaussianBlur(3))
    alpha = np.asarray(body.split()[3]).astype(np.float32) * (np.asarray(hole).astype(np.float32) / 255.0)
    body.putalpha(Image.fromarray(alpha.astype(np.uint8), mode="L"))
    body.save(target / "body.png")

    left = figure.crop(_scale(HAIR_LEFT_BOX))
    left = _feather_edge(_feather_bottom(left, 40 * UPSCALE), 10 * UPSCALE, "right")
    left.save(target / "hair_left.png")

    right = figure.crop(_scale(HAIR_RIGHT_BOX))
    right = _feather_edge(_feather_bottom(right, 40 * UPSCALE), 10 * UPSCALE, "left")
    right.save(target / "hair_right.png")

    manifest: dict[str, Any] = {
        "source": source.name,
        "upscale": UPSCALE,
        "figure": {"width": figure.width, "height": figure.height},
        "head_box": _scale(HEAD_BOX),
        "neck_pivot": [NECK_PIVOT[0] * UPSCALE, NECK_PIVOT[1] * UPSCALE],
        "eye_left": _scale(EYE_LEFT),
        "eye_right": _scale(EYE_RIGHT),
        "mouth_box": _scale(MOUTH_BOX),
        "brow_band": _scale(BROW_BAND),
        "hair_left_box": _scale(HAIR_LEFT_BOX),
        "hair_right_box": _scale(HAIR_RIGHT_BOX),
        "torso_top": TORSO_TOP * UPSCALE,
        "hip_y": HIP_Y * UPSCALE,
        "floor_y": FLOOR_Y * UPSCALE,
    }
    (target / "parts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Нарезка листа персонажа на слои")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, default=TARGET)
    args = parser.parse_args()

    manifest = build(args.source, args.target)
    print(f"слои готовы: {args.target}")
    print(f"фигура {manifest['figure']['width']}×{manifest['figure']['height']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
