#!/usr/bin/env python3
"""Render ANZU Inno Setup wizard images and the pulsing glow frames.

Re-run after a palette or layout change, then commit the PNGs:

    python3 installer/windows/assets/render_wizard_assets.py

Colors and motion are copied from the portal UI (those files are reference
only; this script does not modify them):

- frontend/src/hud/hud-v2.css
  --hud-bg #05070a, --hud-cyan #67dcff, panel #0a0f15
  .hud-brand-mark is an 8px disc with box-shadow 0 0 14px rgba(103, 220, 255, 0.72)
  .hud-top-left strong is #f2fbff with letter-spacing 0.19em
- frontend/src/boot/bootNova.css
  a starting .boot-nova-dot is #67dcff
  boot-dot-pulse is 1.1s ease-in-out infinite:
  0% and 100% are scale 0.85 / opacity 0.65, 50% is scale 1.2 / opacity 1
- frontend/src/index.css
  --gold #d4a017, --muted #9aa3ad

Wizard bitmap sizes are the union of the Inno Setup 6 image areas from before
and after 6.6.0. Setup picks the file closest to the image area, so 100% and
150% DPI land on an exact asset on both generations of the compiler.
"""

from __future__ import annotations

import argparse
import math
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
ISS = ROOT.parent / "Jarvis.iss"
FONT_DIR = ROOT / "fonts"
SEMI = FONT_DIR / "AnzuWizardSans-SemiBold.ttf"
REGULAR = FONT_DIR / "AnzuWizardSans-Regular.ttf"

# HUD / portal palette.
BG = (5, 7, 10, 255)  # #05070a
PANEL = (10, 15, 21, 255)  # #0a0f15
CYAN = (103, 220, 255, 255)  # #67dcff
CYAN_SOFT = (40, 147, 184, 255)
STAR = (196, 239, 255, 255)
WORD = (242, 251, 255, 255)  # #f2fbff
GOLD = (212, 160, 23, 255)  # #d4a017
MUTED = (154, 163, 173, 255)  # #9aa3ad
LINE = (143, 218, 239, 255)

# .hud-brand-mark is 8px. Frames are 192px and the wizard shows them at 64px,
# so the disc stays 8px at 100% DPI (8 * 192/64 = 24).
GLOW_SIZE = 192
CORE_DIAMETER = 24.0
# CSS blur-radius 14px. Pillow's GaussianBlur radius is sigma, and the CSS
# blur-radius is about 2*sigma. Scale 192/64 turns 14 screen px into 42.
GLOW_BLUR_SIGMA = 14.0 / 2.0 * (GLOW_SIZE / 64.0)
GLOW_SHADOW_ALPHA = 0.72
FRAME_COUNT = 16
PULSE_MS = 1100
INTERVAL_MS = 69  # round(1100 / 16) = 68.75
SCALE_MIN = 0.85
SCALE_MAX = 1.2
OPACITY_MIN = 0.65
OPACITY_MAX = 1.0
PEAK_FRAME = FRAME_COUNT // 2

# Inno Setup 6 WizardImageFile areas (classic ratios, pre-6.6 and 6.6+).
LARGE_SIZES = (
    (164, 314),
    (202, 386),
    (240, 459),
    (269, 515),
    (290, 556),
    (315, 604),
    (336, 643),
    (403, 772),
    (430, 824),
)
# WizardSmallImageFile areas, same two generations. 58 is 100% on both.
SMALL_SIZES = (58, 71, 77, 85, 97, 103, 112, 116, 124, 129, 143, 147, 159)


def app_version() -> str:
    text = ISS.read_text(encoding="utf-8")
    match = re.search(r'#define MyAppVersion "([^"]+)"', text)
    if not match:
        raise SystemExit(f"MyAppVersion not found in {ISS}")
    return match.group(1)


def ease_in_out(t: float) -> float:
    """CSS ease-in-out approximated with a cosine, matching the keyframe ends."""
    t = min(1.0, max(0.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def pulse_amounts(frame: int) -> tuple[float, float]:
    """boot-dot-pulse: dim at the ends of the 1.1s loop, bright at the middle."""
    t = frame / FRAME_COUNT
    if t <= 0.5:
        eased = ease_in_out(t / 0.5)
    else:
        eased = ease_in_out((1.0 - t) / 0.5)
    opacity = OPACITY_MIN + (OPACITY_MAX - OPACITY_MIN) * eased
    scale = SCALE_MIN + (SCALE_MAX - SCALE_MIN) * eased
    return opacity, scale


def render_glow_frame(frame: int) -> Image.Image:
    opacity, scale = pulse_amounts(frame)
    ss = 2
    canvas = GLOW_SIZE * ss
    shadow = Image.new("L", (canvas, canvas), 0)
    draw = ImageDraw.Draw(shadow)
    radius = (CORE_DIAMETER / 2.0) * scale * ss
    cx = canvas / 2.0
    box = (cx - radius, cx - radius, cx + radius, cx + radius)
    draw.ellipse(box, fill=255)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=GLOW_BLUR_SIGMA * scale * ss))
    alpha = shadow.point(lambda p: int(p * GLOW_SHADOW_ALPHA * opacity))
    colored = Image.merge(
        "RGBA",
        (
            Image.new("L", (canvas, canvas), CYAN[0]),
            Image.new("L", (canvas, canvas), CYAN[1]),
            Image.new("L", (canvas, canvas), CYAN[2]),
            alpha,
        ),
    )
    core = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    core_draw = ImageDraw.Draw(core)
    # The HUD disc is solid cyan; a little white in the middle keeps it luminous.
    core_draw.ellipse(box, fill=(214, 246, 255, int(round(255 * opacity))))
    colored.alpha_composite(core)
    return colored.resize((GLOW_SIZE, GLOW_SIZE), Image.Resampling.LANCZOS)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=max(8, size))


def _tracked_width(text: str, font: ImageFont.FreeTypeFont, tracking: float) -> float:
    if not text:
        return 0.0
    width = 0.0
    for index, char in enumerate(text):
        width += font.getlength(char)
        if index != len(text) - 1:
            width += tracking
    return width


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    tracking: float,
) -> None:
    x, y = xy
    for index, char in enumerate(text):
        draw.text((x, y), char, font=font, fill=fill)
        x += font.getlength(char)
        if index != len(text) - 1:
            x += tracking


def _paste_center(base: Image.Image, sprite: Image.Image, center: tuple[int, int]) -> None:
    left = int(round(center[0] - sprite.width / 2))
    top = int(round(center[1] - sprite.height / 2))
    base.alpha_composite(sprite, (left, top))


def _radial_wash(width: int, height: int) -> Image.Image:
    """Soft cyan field from hud-app's upper radial gradient, kept faint."""
    wash = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = wash.load()
    cx = width * 0.50
    cy = height * 0.34
    rx = width * 0.72
    ry = height * 0.42
    for y in range(height):
        for x in range(width):
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            dist = math.hypot(dx, dy)
            if dist >= 1:
                continue
            strength = (1.0 - dist) ** 2
            pixels[x, y] = (*CYAN_SOFT[:3], int(36 * strength))
    return wash


def _stars(width: int, height: int) -> Image.Image:
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rng = random.Random(107)
    count = max(18, (width * height) // 4500)
    for _ in range(count):
        x = rng.randrange(width)
        y = rng.randrange(height)
        alpha = rng.choice((50, 70, 96, 128))
        if rng.random() < 0.82:
            draw.point((x, y), fill=(*STAR[:3], alpha))
        else:
            draw.ellipse((x, y, x + 1, y + 1), fill=(*STAR[:3], alpha))
    return layer


def render_large(width: int, height: int, glow: Image.Image, version: str) -> Image.Image:
    image = Image.new("RGBA", (width, height), BG)
    image.alpha_composite(_radial_wash(width, height))
    image.alpha_composite(_stars(width, height))
    draw = ImageDraw.Draw(image)

    rail_x = max(6, int(round(width * 0.085)))
    rail_w = max(1, width // 140)
    draw.line(
        (rail_x, int(height * 0.08), rail_x, int(height * 0.92)),
        fill=(*GOLD[:3], 120),
        width=rail_w,
    )

    mark = glow.resize((max(48, int(width * 0.42)),) * 2, Image.Resampling.LANCZOS)
    _paste_center(image, mark, (width // 2, int(height * 0.34)))

    word = "ANZU"
    word_size = max(18, int(width * 0.155))
    word_font = _font(SEMI, word_size)
    tracking = word_font.size * 0.19
    while word_size > 14 and _tracked_width(word, word_font, tracking) > width * 0.78:
        word_size -= 1
        word_font = _font(SEMI, word_size)
        tracking = word_font.size * 0.19
    word_w = _tracked_width(word, word_font, tracking)
    word_x = (width - word_w) / 2
    word_y = int(height * 0.34) + mark.height // 2 + int(height * 0.02)
    _draw_tracked(draw, (word_x, word_y), word, word_font, WORD, tracking)

    rule_y = word_y + int(word_font.size * 1.35)
    rule_w = int(width * 0.28)
    draw.line(
        ((width - rule_w) // 2, rule_y, (width + rule_w) // 2, rule_y),
        fill=(*CYAN[:3], 160),
        width=max(1, height // 380),
    )

    version_font = _font(REGULAR, max(11, int(width * 0.062)))
    version_w = version_font.getlength(version)
    draw.text(
        ((width - version_w) / 2, height * 0.88),
        version,
        font=version_font,
        fill=(*MUTED[:3], 230),
    )
    return image


def render_small(size: int, glow: Image.Image) -> Image.Image:
    image = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(image)
    inset = max(1, size // 14)
    radius = max(4, size // 5)
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=radius,
        fill=PANEL,
        outline=(*LINE[:3], 90),
        width=max(1, size // 40),
    )
    mark = glow.resize((int(size * 0.78),) * 2, Image.Resampling.LANCZOS)
    _paste_center(image, mark, (size // 2, size // 2))
    return image


def glow_strip(frames: list[Image.Image]) -> Image.Image:
    pad = 16
    cell = 96
    width = pad + (cell + pad) * len(frames)
    image = Image.new("RGBA", (width, cell + pad * 2), BG)
    for index, frame in enumerate(frames):
        sprite = frame.resize((cell, cell), Image.Resampling.LANCZOS)
        image.alpha_composite(sprite, (pad + index * (cell + pad), pad))
    return image


def write_png(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def render_all(out_dir: Path, preview_dir: Path | None = None) -> None:
    version = app_version()
    frames = [render_glow_frame(index) for index in range(FRAME_COUNT)]
    glow_dir = out_dir / "glow"
    for index, frame in enumerate(frames):
        write_png(glow_dir / f"glow-{index:02d}.png", frame)

    peak = frames[PEAK_FRAME]
    for width, height in LARGE_SIZES:
        write_png(out_dir / f"wizard-large-{width}x{height}.png", render_large(width, height, peak, version))
    for size in SMALL_SIZES:
        write_png(out_dir / f"wizard-small-{size}.png", render_small(size, peak))

    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        write_png(preview_dir / "wizard-large-100.png", render_large(202, 386, peak, version))
        write_png(preview_dir / "wizard-large-150.png", render_large(336, 643, peak, version))
        write_png(preview_dir / "wizard-small-100.png", render_small(58, peak))
        write_png(preview_dir / "wizard-small-150.png", render_small(97, peak))
        write_png(preview_dir / "glow-strip.png", glow_strip(frames))
        write_png(preview_dir / "glow-peak.png", peak)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT, help="Directory for wizard PNGs")
    parser.add_argument("--preview-dir", type=Path, default=None, help="Optional preview sheet directory")
    args = parser.parse_args()
    render_all(args.out, args.preview_dir)


if __name__ == "__main__":
    main()
