"""Generate PollFiller.app's icon: a calendar with a checkmark on a gradient
squircle. Renders a 1024px master PNG; build_icon.sh turns it into AppIcon.icns.

    python assets/make_icon.py assets/icon_master.png
"""
from __future__ import annotations

import sys

from PIL import Image, ImageDraw


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Vertical gradient (indigo -> violet), masked to a macOS-style squircle.
    top, bottom = (74, 108, 247), (146, 73, 227)
    grad = Image.new("RGB", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        gd.line([(0, y), (size, y)], fill=_lerp(top, bottom, y / (size - 1)))

    pad = round(size * 0.085)
    sq = size - 2 * pad
    radius = round(sq * 0.2237)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [pad, pad, size - pad, size - pad], radius=radius, fill=255
    )
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # Calendar body (white, slightly above center to leave room for the check).
    cw, ch = round(sq * 0.60), round(sq * 0.56)
    cx = pad + (sq - cw) // 2
    cy = pad + round(sq * 0.16)
    body = [cx, cy, cx + cw, cy + ch]
    br = round(cw * 0.09)
    # soft shadow
    sh = round(size * 0.012)
    d.rounded_rectangle([b + sh for b in body], radius=br, fill=(40, 30, 90, 70))
    d.rounded_rectangle(body, radius=br, fill=(255, 255, 255, 255))

    # Red header bar.
    hh = round(ch * 0.26)
    header = (235, 64, 52)
    d.rounded_rectangle([cx, cy, cx + cw, cy + hh + br], radius=br, fill=header)
    d.rectangle([cx, cy + hh, cx + cw, cy + hh + br], fill=(255, 255, 255, 255))
    d.rectangle([cx, cy + round(hh * 0.5), cx + cw, cy + hh], fill=header)

    # Binder rings.
    rw, rh = round(cw * 0.05), round(hh * 0.62)
    ry = cy - round(rh * 0.45)
    for fx in (0.30, 0.70):
        rx = cx + round(cw * fx)
        d.rounded_rectangle(
            [rx - rw, ry, rx + rw, ry + rh], radius=rw, fill=(255, 255, 255, 255)
        )

    # Faint day-grid dots in the body.
    grid_top = cy + hh + round(ch * 0.14)
    grid_bottom = cy + ch - round(ch * 0.12)
    dot = round(cw * 0.045)
    cols, rows = 4, 3
    gx0, gx1 = cx + round(cw * 0.16), cx + cw - round(cw * 0.16)
    for r in range(rows):
        for c in range(cols):
            px = gx0 + round((gx1 - gx0) * (c / (cols - 1)))
            py = grid_top + round((grid_bottom - grid_top) * (r / (rows - 1)))
            d.ellipse(
                [px - dot, py - dot, px + dot, py + dot], fill=(206, 212, 224, 255)
            )

    # Green check badge, bottom-right, overlapping the calendar.
    bd = round(sq * 0.40)
    bx = cx + cw - round(bd * 0.62)
    by = cy + ch - round(bd * 0.62)
    d.ellipse(
        [bx - sh, by - sh, bx + bd + sh, by + bd + sh], fill=(20, 60, 30, 70)
    )  # shadow
    d.ellipse([bx, by, bx + bd, by + bd], fill=(46, 204, 113, 255))
    d.ellipse(
        [bx, by, bx + bd, by + bd], outline=(255, 255, 255, 255), width=round(bd * 0.06)
    )

    # Checkmark stroke.
    lw = round(bd * 0.12)
    p1 = (bx + round(bd * 0.28), by + round(bd * 0.52))
    p2 = (bx + round(bd * 0.44), by + round(bd * 0.68))
    p3 = (bx + round(bd * 0.74), by + round(bd * 0.34))
    d.line([p1, p2, p3], fill=(255, 255, 255, 255), width=lw, joint="curve")
    for p in (p1, p2, p3):
        d.ellipse(
            [p[0] - lw // 2, p[1] - lw // 2, p[0] + lw // 2, p[1] + lw // 2],
            fill=(255, 255, 255, 255),
        )

    return img


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "assets/icon_master.png"
    make(1024).save(out)
    print("wrote", out)
