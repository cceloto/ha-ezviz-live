"""Generate the brand assets (integration icon/logo) and the README banner.

Usage: python tools/make_brand.py <dir with Poppins-SemiBold.ttf, Poppins-Medium.ttf, Poppins-Regular.ttf>

Poppins is SIL Open Font License (https://fonts.google.com/specimen/Poppins); it is only used to render, not shipped.
Requires Pillow and numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "ezviz_live" / "brand"
IMAGES = ROOT / "docs" / "images"
SS = 4  # supersampling factor

BLUE = (11, 95, 255)
CYAN = (0, 194, 209)
NAVY = (10, 32, 84)
LENS_A = (30, 107, 255)
LENS_B = (56, 212, 255)
RED = (255, 59, 48)
WHITE = (255, 255, 255)
INK = (22, 33, 52)
LIVE_LIGHT_A = (110, 190, 255)  # "Live" on dark backgrounds (banner)
LIVE_LIGHT_B = (90, 235, 225)


def gradient(size: tuple[int, int], a: tuple, b: tuple, angle_deg: float = 45) -> Image.Image:
    """Linear gradient from a (top-left) to b (bottom-right)."""
    w, h = size
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.deg2rad(angle_deg)
    proj = x * np.cos(t) + y * np.sin(t)
    proj = (proj - proj.min()) / (proj.max() - proj.min())
    rgb = np.empty((h, w, 3), np.float32)
    for i in range(3):
        rgb[..., i] = a[i] + (b[i] - a[i]) * proj
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")


def mask_draw(size: tuple[int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    m = Image.new("L", size, 0)
    return m, ImageDraw.Draw(m)


def icon(px: int) -> Image.Image:
    """Square icon: gradient squircle, white cloud, camera lens, red live dot."""
    n = px * SS
    u = n / 1000  # design units: 1000 × 1000

    def box(cx, cy, r):
        return [(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u]

    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))

    # badge
    badge_mask, d = mask_draw((n, n))
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=230 * u, fill=255)
    out.paste(gradient((n, n), BLUE, CYAN), (0, 0), badge_mask)

    # soft shadow under the cloud
    shadow_mask, d = mask_draw((n, n))
    for cx, cy, r in ((330, 590, 150), (500, 480, 210), (690, 570, 165)):
        d.ellipse(box(cx, cy, r), fill=90)
    d.rounded_rectangle([180 * u, 570 * u, 840 * u, 740 * u], radius=85 * u, fill=90)
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(28 * u))
    out.paste(Image.new("RGBA", (n, n), NAVY + (255,)), (0, 0),
              Image.fromarray((np.array(shadow_mask) * 0.55).astype(np.uint8)))

    # cloud
    cloud_mask, d = mask_draw((n, n))
    for cx, cy, r in ((330, 560, 150), (500, 450, 210), (690, 540, 165)):
        d.ellipse(box(cx, cy, r), fill=255)
    d.rounded_rectangle([180 * u, 540 * u, 840 * u, 710 * u], radius=85 * u, fill=255)
    out.paste(Image.new("RGBA", (n, n), WHITE + (255,)), (0, 0), cloud_mask)

    # lens
    d = ImageDraw.Draw(out)
    d.ellipse(box(505, 545, 158), fill=NAVY)
    lens_mask, md = mask_draw((n, n))
    md.ellipse(box(505, 545, 112), fill=255)
    out.paste(gradient((n, n), LENS_A, LENS_B, 60), (0, 0), lens_mask)
    d.ellipse(box(505, 545, 56), fill=NAVY)
    d.ellipse(box(468, 506, 24), fill=WHITE)

    # live dot
    d.ellipse(box(770, 290, 92), fill=WHITE)
    d.ellipse(box(770, 290, 70), fill=RED)

    return out.resize((px, px), Image.LANCZOS)


def trim(img: Image.Image) -> Image.Image:
    return img.crop(img.getbbox())


def wordmark(height: int, color: tuple, fonts: Path, live: tuple = (BLUE, CYAN)) -> Image.Image:
    """'EZVIZ Live' text block, `height` px tall (cap height drives the size)."""
    n = height * SS
    bold = ImageFont.truetype(str(fonts / "Poppins-SemiBold.ttf"), int(n * 1.05))
    light = ImageFont.truetype(str(fonts / "Poppins-Regular.ttf"), int(n * 1.05))
    canvas = Image.new("RGBA", (n * 8, n * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((0, 0), "EZVIZ", font=bold, fill=color + (255,))
    x = d.textlength("EZVIZ ", font=bold)
    # "Live" in the brand gradient
    live_mask, md = mask_draw(canvas.size)
    md.text((x, 0), "Live", font=light, fill=255)
    canvas.paste(gradient(canvas.size, *live, 0), (0, 0), live_mask)
    img = trim(canvas)
    return img.resize((max(1, img.width // SS), max(1, img.height // SS)), Image.LANCZOS)


def logo(height: int, text_color: tuple, fonts: Path) -> Image.Image:
    """Landscape logo: icon + wordmark, trimmed, `height` px tall."""
    ic = icon(height)
    text = wordmark(int(height * 0.42), text_color, fonts)
    gap = int(height * 0.22)
    out = Image.new("RGBA", (ic.width + gap + text.width, height), (0, 0, 0, 0))
    out.paste(ic, (0, 0), ic)
    out.paste(text, (ic.width + gap, (height - text.height) // 2), text)
    return trim(out)


def background(w: int, h: int, *, rounded: bool) -> Image.Image:
    """Navy-to-blue gradient with a cyan glow on the left; rounded card or full bleed."""
    n_w, n_h = w * SS, h * SS
    bg = gradient((n_w, n_h), (8, 24, 64), (6, 78, 140), 20)
    glow_mask, d = mask_draw((n_w, n_h))
    d.ellipse([-0.05 * n_w, -0.4 * n_h, 0.45 * n_w, 1.4 * n_h], fill=70)
    bg.paste(Image.new("RGBA", (n_w, n_h), CYAN + (255,)), (0, 0),
             glow_mask.filter(ImageFilter.GaussianBlur(n_h * 0.25)))
    if rounded:
        card_mask, d = mask_draw((n_w, n_h))
        d.rounded_rectangle([0, 0, n_w - 1, n_h - 1], radius=int(n_h * 0.12), fill=255)
        out = Image.new("RGBA", (n_w, n_h), (0, 0, 0, 0))
        out.paste(bg, (0, 0), card_mask)
        bg = out
    return bg.resize((w, h), Image.LANCZOS)


def content(w: int, h: int, fonts: Path) -> Image.Image:
    """Icon, wordmark, tagline and feature chips on a transparent w × h layer (layout scales with h)."""
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ic = icon(int(h * 0.56))
    out.paste(ic, (int(h * 0.22), (h - ic.height) // 2), ic)
    x = int(h * 0.22) + ic.width + int(h * 0.14)

    title = wordmark(int(h * 0.17), WHITE, fonts, live=(LIVE_LIGHT_A, LIVE_LIGHT_B))
    out.paste(title, (x, int(h * 0.24)), title)
    # translucent shapes go on their own layer and are composited; drawing them directly would punch holes
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sub = ImageFont.truetype(str(fonts / "Poppins-Regular.ttf"), int(h * 0.075))
    d.text((x, int(h * 0.50)), "Cloud live view for EZVIZ cameras in Home Assistant",
           font=sub, fill=(214, 228, 255, 255))
    chip_font = ImageFont.truetype(str(fonts / "Poppins-Medium.ttf"), int(h * 0.055))
    cx, cy = x, int(h * 0.68)
    for label in ("Battery-friendly", "No extra login", "HLS · H.265"):
        tw = d.textlength(label, font=chip_font)
        pad_x, ch = int(h * 0.045), int(h * 0.11)
        d.rounded_rectangle([cx, cy, cx + tw + 2 * pad_x, cy + ch], radius=ch // 2,
                            fill=(255, 255, 255, 30), outline=(255, 255, 255, 110), width=max(1, h // 200))
        d.text((cx + pad_x, cy + ch / 2), label, font=chip_font, fill=WHITE + (255,), anchor="lm")
        cx += int(tw + 2 * pad_x + h * 0.04)
    return Image.alpha_composite(out, layer)


def banner(w: int, h: int, fonts: Path) -> Image.Image:
    """README / HACS banner: rounded card, readable on light and dark themes."""
    return Image.alpha_composite(background(w, h, rounded=True), content(w, h, fonts))


def social_preview(fonts: Path) -> Image.Image:
    """GitHub social preview (1280 × 640): shown when the repository link is shared in forums and chats."""
    out = background(1280, 640, rounded=False)
    out.alpha_composite(content(1280, 400, fonts), (0, 120))
    return out


def main() -> None:
    fonts = Path(sys.argv[1])
    BRAND.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    icon(256).save(BRAND / "icon.png", optimize=True)
    icon(512).save(BRAND / "icon@2x.png", optimize=True)
    logo(128, INK, fonts).save(BRAND / "logo.png", optimize=True)
    logo(256, INK, fonts).save(BRAND / "logo@2x.png", optimize=True)
    logo(128, WHITE, fonts).save(BRAND / "dark_logo.png", optimize=True)
    logo(256, WHITE, fonts).save(BRAND / "dark_logo@2x.png", optimize=True)
    banner(1280, 400, fonts).save(IMAGES / "banner.png", optimize=True)
    social_preview(fonts).convert("RGB").save(IMAGES / "social-preview.png", optimize=True)
    print("ok")


if __name__ == "__main__":
    main()
