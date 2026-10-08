"""Contracts for the owner-shell black bands.

The face and torso bars were failed WebView2 compositor tiles: an opaque black
canvas clear, sampled through a CSS mask and backdrop-filter. The right-hand
panel was that same clear beside a width-capped chat column. Headless Chrome
can prove the replacement edge overlay does not cut the figure or lay a
full-frame scrim. It cannot reproduce the WebView2 tile failure itself.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
RENDERERS = FRONTEND / "src" / "presence" / "renderers"


def _rule(css: str, selector: str) -> str:
    start = css.index(selector)
    open_brace = css.index("{", start)
    depth = 0
    for index, char in enumerate(css[open_brace:], start=open_brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace + 1 : index]
    raise AssertionError(f"unclosed rule {selector}")


def test_canvas_is_unmasked_and_clear_alpha_stays_zero():
    humanoid = (RENDERERS / "humanoid-presence.css").read_text(encoding="utf-8")
    stage = (RENDERERS / "MorphablePresenceStage.tsx").read_text(encoding="utf-8")
    hud = (FRONTEND / "src" / "hud" / "hud-v2.css").read_text(encoding="utf-8")

    assert "mask-image" not in humanoid
    fade = _rule(humanoid, ".jarvis-presence-humanoid::after {")
    assert "transparent 4%" in fade and "transparent 94%" in fade

    assert "setClearColor(0x000000, 1)" not in stage
    assert stage.count("setClearColor(0x000000, 0)") == 2
    assert "uSampleEnergy: { value: FIGURE_SAMPLE_ENERGY }" in stage

    bubble = _rule(hud, ".hud-bubble {")
    composer = _rule(hud, ".hud-composer {")
    assert "backdrop-filter: none" in bubble
    assert "backdrop-filter: blur" not in bubble
    assert "backdrop-filter: none" in composer
    assert "backdrop-filter: blur" not in composer

    chat = _rule(hud, ".hud-home:has(.jarvis-presence-stage) > .hud-chat {")
    assert "min(1000px" not in chat
    assert "920px" not in chat
    assert "max-width: none" in chat
    center = _rule(hud, ".hud-center:has(.jarvis-presence-stage) {")
    assert "overflow: clip" in center
    assert "scrollbar-width: none" in center


def _chrome() -> str | None:
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def _capture(html: Path, png: Path) -> None:
    chrome = _chrome()
    if chrome is None:
        pytest.skip("headless chrome is not installed")
    png.parent.mkdir(parents=True, exist_ok=True)
    profile = png.parent / "profile"
    if profile.exists():
        shutil.rmtree(profile)
    cmd = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--user-data-dir={profile}",
        "--window-size=1400,900",
        f"--screenshot={png}",
        "--virtual-time-budget=2000",
        html.as_uri(),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 15
    try:
        while time.time() < deadline:
            if png.exists() and png.stat().st_size > 1000:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.2)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
    if not png.exists() or png.stat().st_size < 1000:
        raise AssertionError(f"headless chrome did not write {png}")


def _assert_no_mid_bands(png: Path) -> None:
    from PIL import Image

    image = Image.open(png).convert("RGB")
    width, height = image.size
    pixels = image.load()
    assert pixels is not None
    dark_rows: list[int] = []
    y0, y1 = int(height * 0.12), int(height * 0.88)
    for y in range(y0, y1):
        red, green, blue = pixels[width // 2, y]
        if red < 18 and green < 18 and blue < 18:
            dark_rows.append(y)
    assert not dark_rows, f"mid-figure black rows in {png.name}: {dark_rows[:12]}"

    samples: list[float] = []
    for y in range(int(height * 0.25), int(height * 0.75), 6):
        for x in range(int(width * 0.35), int(width * 0.65), 6):
            red, green, blue = pixels[x, y]
            samples.append((red + green + blue) / 3)
    mean = sum(samples) / len(samples)
    assert mean > 90, f"{png.name} center looks like a full-frame scrim (mean {mean:.1f})"

    top = pixels[width // 2, 1]
    assert max(top) < 80, f"{png.name} lost the edge fade, top pixel {top}"


@pytest.mark.parametrize("galaxy", [False, True])
def test_edge_overlay_does_not_band_or_scrim_the_figure(galaxy: bool, tmp_path: Path):
    suffix = "galaxy" if galaxy else "helmet"
    html = tmp_path / f"{suffix}.html"
    png = tmp_path / f"{suffix}.png"
    galaxy_attr = ' data-galaxy="true"' if galaxy else ""
    css = (RENDERERS / "humanoid-presence.css").resolve().as_uri()
    html.write_text(
        f"""<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="{css}">
  <style>
    html, body {{ margin: 0; background: #010308; }}
    .proof {{
      width: 1400px;
      height: 900px;
    }}
    .figure {{
      position: absolute;
      inset: 0;
      background: #3ec8ff;
    }}
  </style>
</head>
<body>
  <div class="proof jarvis-presence-humanoid"{galaxy_attr}>
    <div class="figure"></div>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )
    _capture(html, png)
    _assert_no_mid_bands(png)
