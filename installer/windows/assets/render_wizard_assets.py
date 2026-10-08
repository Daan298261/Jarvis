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

# Official mark is Logo_black.png (1254×1254, gold on black). The wizard shows
# the downscale: 28px at 100% DPI and 42px at 150% (ScaleY(28)).
# Two lines replace the em dash so the credit does not depend on that glyph.
SPONSOR_LINES = (
    "Made in the Netherlands",
    "Sponsored by Black Grid Publishing",
)
SPONSOR_URL = "https://blackgridpublishing.com"
LOGO_100 = 28
LOGO_150 = 42
# Design pixels. Matches ScaleX(16) in Jarvis.iss, the clear gap before Back.
SPONSOR_GAP_BEFORE_BACK = 16


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


def key_black(source: Image.Image) -> Image.Image:
    """Turn the official logo's black field transparent and keep the gold art."""
    src = source.convert("RGBA")
    out = Image.new("RGBA", src.size, (0, 0, 0, 0))
    sp = src.load()
    dp = out.load()
    width, height = src.size
    for y in range(height):
        for x in range(width):
            r, g, b, _a = sp[x, y]
            peak = max(r, g, b)
            if peak < 24:
                continue
            alpha = min(255, int((peak - 24) / 36.0 * 255))
            dp[x, y] = (r, g, b, alpha)
    return out


def flatten_logo(source: Image.Image, size: int) -> Image.Image:
    keyed = key_black(source)
    big = keyed.resize((size * 4, size * 4), Image.Resampling.LANCZOS)
    small = big.resize((size, size), Image.Resampling.LANCZOS)
    plate = Image.new("RGBA", (size, size), BG)
    plate.alpha_composite(small)
    return plate


def find_logo_source(explicit: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.append(ROOT / "sponsor" / "Logo_black.png")
    candidates.append(Path("/tmp/bgp-logo/Logo_black.png"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def render_sponsor_logos(source: Path, out_dir: Path) -> dict[int, Image.Image]:
    official = Image.open(source)
    logos = {
        LOGO_100: flatten_logo(official, LOGO_100),
        LOGO_150: flatten_logo(official, LOGO_150),
    }
    sponsor_dir = out_dir / "sponsor"
    write_png(sponsor_dir / "bgp-logo-100.png", logos[LOGO_100])
    write_png(sponsor_dir / "bgp-logo-150.png", logos[LOGO_150])
    return logos


def render_wizard_page(
    kind: str,
    scale: float,
    sidebar: Image.Image,
    glow: Image.Image,
    logo: Image.Image,
) -> Image.Image:
    """Welcome or Finished client, plus a title bar, at 100% (scale=1) or 150%."""
    client_w = round(497 * scale)
    client_h = round(360 * scale)
    title_h = round(28 * scale)
    image = Image.new("RGBA", (client_w, title_h + client_h), BG)
    draw = ImageDraw.Draw(image)
    title_font = _font(SEMI, max(11, round(12 * scale)))
    draw.text((round(12 * scale), round(6 * scale)), "Setup - ANZU", font=title_font, fill=WORD)

    side_w = round(164 * scale)
    side_h = round(314 * scale)
    side = sidebar.resize((side_w, side_h), Image.Resampling.LANCZOS)
    image.alpha_composite(side, (0, title_h))

    content_x = round(176 * scale)
    glow_size = round(64 * scale)
    glow_sprite = glow.resize((glow_size, glow_size), Image.Resampling.LANCZOS)
    image.alpha_composite(glow_sprite, (content_x, title_h + round(16 * scale)))

    heading_font = _font(SEMI, max(13, round(16 * scale)))
    body_font = _font(REGULAR, max(11, round(12 * scale)))
    heading_y = title_h + round(84 * scale)
    if kind == "welcome":
        heading = "Welcome to ANZU"
        body = "This will install ANZU on your computer.\nClick Next to continue, or Cancel to exit Setup."
    else:
        heading = "ANZU setup is complete"
        body = "Setup has finished installing ANZU on your computer.\nClick Finish to exit Setup."
    draw.text((content_x, heading_y), heading, font=heading_font, fill=WORD)
    body_y = heading_y + round(36 * scale)
    for line in body.split("\n"):
        draw.text((content_x, body_y), line, font=body_font, fill=(*MUTED[:3], 230))
        body_y += round(18 * scale)

    # Button strip under the sidebar. Credit sits left of Back.
    button_w = round(75 * scale)
    button_h = round(23 * scale)
    button_top = title_h + round(327 * scale)
    gap = round(10 * scale)
    cancel_left = client_w - gap - button_w
    next_left = cancel_left - gap - button_w
    back_left = next_left - button_w
    button_font = _font(REGULAR, max(10, round(11 * scale)))
    for left, caption, enabled in (
        (back_left, "Back", False),
        (next_left, "Next" if kind == "welcome" else "Finish", True),
        (cancel_left, "Cancel", True),
    ):
        draw.rounded_rectangle(
            (left, button_top, left + button_w, button_top + button_h),
            radius=max(2, round(3 * scale)),
            fill=PANEL,
            outline=(*MUTED[:3], 80 if enabled else 40),
        )
        fill = (*WORD[:3], 230) if enabled else (*MUTED[:3], 120)
        caption_w = button_font.getlength(caption)
        draw.text(
            (left + (button_w - caption_w) / 2, button_top + round(4 * scale)),
            caption,
            font=button_font,
            fill=fill,
        )

    logo_size = round(LOGO_100 * scale)
    logo_sprite = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
    logo_left = round(10 * scale)
    logo_top = button_top + (button_h - logo_size) // 2
    image.alpha_composite(logo_sprite, (logo_left, logo_top))

    credit_font = _font(REGULAR, max(9, round(11 * scale)))
    text_left = logo_left + logo_size + round(8 * scale)
    gap_before_back = round(SPONSOR_GAP_BEFORE_BACK * scale)
    text_right_limit = back_left - gap_before_back
    # ScaleY(14) in the installer: two lines match the 28px logo and stay centered.
    line_h = round(14 * scale)
    block_h = line_h * len(SPONSOR_LINES)
    text_top = logo_top + (logo_size - block_h) // 2
    for index, line in enumerate(SPONSOR_LINES):
        line_width = credit_font.getlength(line)
        if text_left + line_width > text_right_limit:
            raise SystemExit(
                f"Sponsor line does not fit before Back at {scale:.0%} DPI: {line!r} "
                f"({line_width:.0f}px, limit {text_right_limit - text_left:.0f}px)"
            )
        draw.text(
            (text_left, text_top + index * line_h),
            line,
            font=credit_font,
            fill=(*MUTED[:3], 230),
        )
    return image


def write_png(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def render_all(out_dir: Path, preview_dir: Path | None = None, logo_source: Path | None = None) -> None:
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

    source = find_logo_source(logo_source)
    logos: dict[int, Image.Image] = {}
    if source is not None:
        logos = render_sponsor_logos(source, out_dir)
    elif (out_dir / "sponsor" / "bgp-logo-100.png").is_file():
        logos = {
            LOGO_100: Image.open(out_dir / "sponsor" / "bgp-logo-100.png").convert("RGBA"),
            LOGO_150: Image.open(out_dir / "sponsor" / "bgp-logo-150.png").convert("RGBA"),
        }

    if preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        write_png(preview_dir / "wizard-large-100.png", render_large(202, 386, peak, version))
        write_png(preview_dir / "wizard-large-150.png", render_large(336, 643, peak, version))
        write_png(preview_dir / "wizard-small-100.png", render_small(58, peak))
        write_png(preview_dir / "wizard-small-150.png", render_small(97, peak))
        write_png(preview_dir / "glow-strip.png", glow_strip(frames))
        write_png(preview_dir / "glow-peak.png", peak)
        if logos:
            side_100 = render_large(164, 314, peak, version)
            side_150 = render_large(246, 471, peak, version)
            write_png(
                preview_dir / "welcome-100.png",
                render_wizard_page("welcome", 1.0, side_100, peak, logos[LOGO_100]),
            )
            write_png(
                preview_dir / "welcome-150.png",
                render_wizard_page("welcome", 1.5, side_150, peak, logos[LOGO_150]),
            )
            write_png(
                preview_dir / "finished-100.png",
                render_wizard_page("finished", 1.0, side_100, peak, logos[LOGO_100]),
            )
            write_png(
                preview_dir / "finished-150.png",
                render_wizard_page("finished", 1.5, side_150, peak, logos[LOGO_150]),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT, help="Directory for wizard PNGs")
    parser.add_argument("--preview-dir", type=Path, default=None, help="Optional preview sheet directory")
    parser.add_argument("--logo", type=Path, default=None, help="Official Logo_black.png (not written into the asset tree)")
    args = parser.parse_args()
    render_all(args.out, args.preview_dir, args.logo)


if __name__ == "__main__":
    main()
