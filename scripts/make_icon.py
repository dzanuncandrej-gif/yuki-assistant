"""Рисует иконку приложения assets/yuki.ico — внешние картинки не нужны.

Эмблема повторяет язык интерфейса: почти чёрный диск, холодное синее свечение по
краю и белая «Y» в центре. Рисуется с четырёхкратным запасом и уменьшается —
так края остаются гладкими даже на 16 пикселях, где Windows показывает иконку в
трее и на панели задач.

    python scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "assets" / "yuki.ico"

SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPER = 4  # во столько раз крупнее рисуем перед уменьшением

DEEP = (6, 10, 20, 255)        # фон диска
GLOW = (96, 178, 255)          # холодное свечение
EDGE = (150, 210, 255, 255)    # тонкий кант
WHITE = (238, 246, 255, 255)   # сама буква


def _letter(draw: ImageDraw.ImageDraw, box: float, width: float) -> None:
    """Буква «Y» из трёх отрезков с круглыми концами."""
    centre = box / 2
    top = box * 0.34
    fork = box * 0.53
    bottom = box * 0.70
    span = box * 0.15
    for start, end in (
        ((centre - span, top), (centre, fork)),
        ((centre + span, top), (centre, fork)),
        ((centre, fork), (centre, bottom)),
    ):
        draw.line((*start, *end), fill=WHITE, width=int(width), joint="curve")
        for point in (start, end):  # круглые концы: line их не рисует
            radius = width / 2
            draw.ellipse(
                (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
                fill=WHITE,
            )


def render(size: int) -> Image.Image:
    box = size * SUPER
    image = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = box * 0.04
    draw.ellipse((inset, inset, box - inset, box - inset), fill=DEEP)

    # свечение: кольцо рисуется отдельно и размывается, иначе край выглядит резким
    halo = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    ring = ImageDraw.Draw(halo)
    ring.ellipse(
        (inset, inset, box - inset, box - inset),
        outline=(*GLOW, 255), width=max(2, int(box * 0.045)),
    )
    halo = halo.filter(ImageFilter.GaussianBlur(box * 0.035))
    image = Image.alpha_composite(image, halo)

    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (inset, inset, box - inset, box - inset),
        outline=EDGE, width=max(1, int(box * 0.016)),
    )

    # мягкий отсвет под буквой — эмблема перестаёт быть плоской
    shine = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    ImageDraw.Draw(shine).ellipse(
        (box * 0.22, box * 0.16, box * 0.78, box * 0.52), fill=(*GLOW, 60)
    )
    image = Image.alpha_composite(image, shine.filter(ImageFilter.GaussianBlur(box * 0.06)))

    glyph = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    _letter(ImageDraw.Draw(glyph), box, max(2.0, box * 0.075))
    # то же свечение, что у кольца: буква светится, а не лежит наклейкой
    aura = glyph.filter(ImageFilter.GaussianBlur(box * 0.03))
    image = Image.alpha_composite(image, aura)
    image = Image.alpha_composite(image, glyph)

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    frames = [render(size) for size in SIZES]
    frames[-1].save(TARGET, format="ICO", sizes=[(s, s) for s in SIZES])
    preview = TARGET.with_suffix(".png")
    frames[-1].save(preview)
    print(f"иконка: {TARGET} ({TARGET.stat().st_size // 1024} КБ), образцы {SIZES}")
    print(f"просмотр: {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
