"""Keep the remote loopback portal's native commands enrolled in Tauri ACL."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src-tauri"

def test_registered_commands_have_manifest_and_loopback_permissions():
    commands = set(re.findall(r"#\[tauri::command\]\s*fn (\w+)", (ROOT / "src/lib.rs").read_text()))
    manifest = set(re.findall(r'"([a-z_]+)"', (ROOT / "build.rs").read_text()))
    capability = json.loads((ROOT / "capabilities/default.json").read_text())
    assert commands == manifest
    assert {"allow-" + name.replace("_", "-") for name in commands} <= set(capability["permissions"])
    assert capability["windows"] == ["main"]
    assert capability["remote"]["urls"] == ["http://127.0.0.1:4780/*", "http://localhost:4780/*"]
