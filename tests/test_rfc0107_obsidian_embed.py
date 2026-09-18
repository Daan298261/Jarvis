"""RFC-0107 embedded Obsidian host — bridge + URI helpers (no Obsidian.exe on Linux)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "frontend" / "src" / "desktop" / "bridge.ts"
URI = ROOT / "frontend" / "src" / "vault" / "obsidianUri.ts"
OBSIDIAN_PAGE = ROOT / "frontend" / "src" / "pages" / "Obsidian.tsx"
TAURI_LIB = ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"
HOST_RS = ROOT / "frontend" / "src-tauri" / "src" / "obsidian_host.rs"


def test_desktop_bridge_exports_obsidian_host_commands():
    text = BRIDGE.read_text(encoding="utf-8")
    for symbol in (
        "obsidianProbe",
        "obsidianEmbedStart",
        "obsidianEmbedResize",
        "obsidianEmbedStop",
        "obsidianFocusNote",
        "obsidianOpenInstall",
        "obsidianBoundVaultPath",
    ):
        assert symbol in text


def test_obsidian_page_is_host_not_custom_editor():
    text = OBSIDIAN_PAGE.read_text(encoding="utf-8")
    assert "obsidian-native-host" in text
    assert "CodeMirror" not in text
    assert "markdown editor" not in text.lower()


def test_tauri_registers_obsidian_commands():
    text = TAURI_LIB.read_text(encoding="utf-8")
    for cmd in (
        "obsidian_probe",
        "obsidian_embed_start",
        "obsidian_embed_stop",
        "obsidian_focus_note",
    ):
        assert cmd in text
    assert "mod obsidian_host" in text


def test_obsidian_host_module_present():
    assert HOST_RS.is_file()
    body = HOST_RS.read_text(encoding="utf-8")
    assert "SetParent" in body
    assert "obsidian://open" in body


def test_obsidian_uri_builder():
    text = URI.read_text(encoding="utf-8")
    assert "buildObsidianOpenUri" in text
    assert "obsidian://open?vault=" in text
