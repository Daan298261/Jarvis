"""Frontend DesktopBridge fallback helpers (Node-free pure checks via file content)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "frontend" / "src" / "desktop" / "bridge.ts"


def test_desktop_bridge_file_exists_and_exports_fallback():
    text = BRIDGE.read_text(encoding="utf-8")
    assert "export const DesktopBridge" in text
    assert "isDesktop()" in text
    assert "restartBackend" in text
    assert "openLogs" in text
    assert "setAutostart" in text
    assert "quitJarvis" in text
    assert "browserBridgeFallback" in text
    # Must not scatter invoke() outside the bridge for core commands — bridge is the adapter.
    assert "getInvoke()" in text


def test_setup_page_exists():
    setup = ROOT / "frontend" / "src" / "pages" / "Setup.tsx"
    assert setup.is_file()
    text = setup.read_text(encoding="utf-8")
    assert "First-run setup" in text
    assert "Finish setup without local model" in text
    assert "Not yet implemented (P3)" in text
