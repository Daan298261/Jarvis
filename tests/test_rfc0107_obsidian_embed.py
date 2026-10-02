"""RFC-0107 embedded Obsidian host — bridge + URI helpers (no Obsidian.exe on Linux)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "frontend" / "src" / "desktop" / "bridge.ts"
URI = ROOT / "frontend" / "src" / "vault" / "obsidianUri.ts"
OBSIDIAN_PAGE = ROOT / "frontend" / "src" / "pages" / "Obsidian.tsx"
SETTINGS = ROOT / "frontend" / "src" / "settings" / "KnowledgeVaultSettingsSection.tsx"
TAURI_LIB = ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"
HOST_RS = ROOT / "frontend" / "src-tauri" / "src" / "obsidian_host.rs"
APP = ROOT / "frontend" / "src" / "App.tsx"
CSS = ROOT / "frontend" / "src" / "styles" / "obsidian-host.css"


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
    # Embed start must surface invoke failures as failed status (not silent null).
    assert 'state: "failed"' in text


def test_obsidian_page_is_host_not_custom_editor():
    text = OBSIDIAN_PAGE.read_text(encoding="utf-8")
    assert "obsidian-native-host" in text
    assert "CodeMirror" not in text
    assert "markdown editor" not in text.lower()
    assert "Open vault in Obsidian" in text
    assert "Open Obsidian in Jarvis Desktop" in text
    assert "Launch Jarvis Desktop" not in text
    assert "second notebook" in text
    assert 'data-testid="obsidian-native-host"' in text
    assert "obsidian-host-overlay" in text
    # Forbidden parallel brain UI signals
    assert "custom note browser" in text.lower() or "No custom note browser" in text


def test_obsidian_page_truthful_browser_surface():
    text = OBSIDIAN_PAGE.read_text(encoding="utf-8")
    assert 'data-testid="obsidian-surface-browser"' in text
    assert "cannot parent" in text
    assert "OBSIDIAN_DOWNLOAD_URL" in text


def test_settings_points_to_obsidian_pane_not_clone():
    text = SETTINGS.read_text(encoding="utf-8")
    assert 'to="/obsidian"' in text
    assert "custom note browser" in text.lower()
    assert "Jarvis Desktop" in text


def test_app_full_bleed_obsidian_route():
    text = APP.read_text(encoding="utf-8")
    assert "isObsidianPath" in text
    assert "obsidian-main" in text
    assert 'path="/obsidian"' in text


def test_obsidian_host_css_fills_hud_and_classic():
    text = CSS.read_text(encoding="utf-8")
    assert ".main.obsidian-main" in text
    assert ".hud-admin-main:has(.obsidian-host-page)" in text
    assert ".obsidian-native-host" in text


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
    assert "OBSIDIAN_DOWNLOAD_URL" in text
    assert "obsidian.md/download" in text
