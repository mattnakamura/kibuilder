"""Draw the kibuilder app icon procedurally with Pillow.

Design: a 2×2 stacking-brick face seen from above. Substrate is PCB green
(KiCad-style); the studs are copper-gold to read as pads, each ringed
with a slightly raised highlight so they look like real raised bumps. A
faint white border on the icon canvas evokes silkscreen.

Outputs a single 1024×1024 PNG; `build_icon.sh` then downsamples it for
the macOS iconset.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
OUT = Path(__file__).resolve().parent.parent / "resources" / "icon_1024.png"

# Palette — KiCad-ish PCB green substrate, copper-gold pads.
BG_OUTER       = (26, 60, 44, 255)   # very dark green border
BG_INNER       = (44, 124, 80, 255)  # PCB green substrate
BG_INNER_DARK  = (32, 92, 60, 255)   # subtle gradient bottom
SILKSCREEN     = (240, 240, 232, 255)
COPPER         = (200, 137, 58, 255) # exposed copper pad
COPPER_LIGHT   = (228, 174, 96, 255) # rim highlight
COPPER_SHADOW  = (130, 80, 30, 255)  # inner shadow
DROP_SHADOW    = (0, 0, 0, 110)


def rounded_rect_mask(size: int, radius: int) -> Image.Image:
    """Return a single-channel mask for a rounded square."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def gradient_fill(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """Vertical linear gradient between two RGBA colors."""
    img = Image.new("RGBA", (size, size), top)
    for y in range(size):
        t = y / max(1, size - 1)
        rgba = tuple(
            int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)
        )
        ImageDraw.Draw(img).line([(0, y), (size, y)], fill=rgba)
    return img


def draw_stud(canvas: Image.Image, cx: int, cy: int, radius: int):
    """Draw one brick stud as a raised copper bump.

    Sphere-shading trick: a dark disc at the full radius, then a lighter
    copper disc inset a little toward the upper-left. The exposed crescent
    of the dark disc reads as the shadowed bottom-right rim of a 3D bump.
    """
    # Soft drop shadow under the stud
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse(
        [cx - radius - 6, cy - radius + 26,
         cx + radius + 6, cy + radius + 40],
        fill=DROP_SHADOW,
    )
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))

    # Dark base disc — becomes the shadow crescent
    d = ImageDraw.Draw(canvas)
    d.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=COPPER_SHADOW,
    )

    # Lit copper face — inset toward the upper-left.
    inset = max(6, radius // 18)
    off = radius // 9
    d.ellipse(
        [cx - radius + inset - off, cy - radius + inset - off,
         cx + radius - inset - off, cy + radius - inset - off],
        fill=COPPER,
    )

    # Soft brighter zone over the upper-left of the face (rolling highlight)
    bright = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    br = int(radius * 0.78)
    bx = cx - radius // 4
    by = cy - radius // 4
    ImageDraw.Draw(bright).ellipse(
        [bx - br, by - br, bx + br, by + br],
        fill=(*COPPER_LIGHT[:3], 200),
    )
    canvas.alpha_composite(bright.filter(ImageFilter.GaussianBlur(28)))

    # Tight specular hotspot (catchlight)
    spec = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sr = max(8, radius // 4)
    sx = cx - radius // 3
    sy = cy - radius // 2
    ImageDraw.Draw(spec).ellipse(
        [sx - sr, sy - sr, sx + sr, sy + sr],
        fill=(255, 245, 210, 230),
    )
    canvas.alpha_composite(spec.filter(ImageFilter.GaussianBlur(10)))


def build_icon() -> Image.Image:
    # Substrate — gradient inside rounded mask, dark border around it
    mask = rounded_rect_mask(SIZE, radius=int(SIZE * 0.21))
    grad = gradient_fill(SIZE, BG_INNER, BG_INNER_DARK)

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(grad, mask=mask)

    # Outer trim (silkscreen-style) — thin lighter border
    border = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bd.rounded_rectangle(
        [20, 20, SIZE - 21, SIZE - 21],
        radius=int(SIZE * 0.20) - 4,
        outline=SILKSCREEN, width=6,
    )
    # Mask the border so it doesn't bleed outside the rounded canvas
    border = Image.composite(
        border, Image.new("RGBA", icon.size, (0, 0, 0, 0)), mask,
    )
    icon.alpha_composite(border)

    # A second very-faint inner border to read as silkscreen pad outlines
    inner = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    ImageDraw.Draw(inner).rounded_rectangle(
        [70, 70, SIZE - 71, SIZE - 71],
        radius=int(SIZE * 0.16),
        outline=(*SILKSCREEN[:3], 70), width=3,
    )
    icon.alpha_composite(inner)

    # 2×2 stud grid, centered, with standard stacking-brick spacing
    stud_r = int(SIZE * 0.16)        # ~165 px radius
    spacing = int(SIZE * 0.21)       # center-to-center / 2
    cx0, cy0 = SIZE // 2 - spacing, SIZE // 2 - spacing
    cx1, cy1 = SIZE // 2 + spacing, SIZE // 2 + spacing
    for cx in (cx0, cx1):
        for cy in (cy0, cy1):
            draw_stud(icon, cx, cy, stud_r)

    return icon


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon = build_icon()
    icon.save(OUT, "PNG")
    print(f"wrote {OUT}  ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
