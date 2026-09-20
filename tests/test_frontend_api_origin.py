from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_portal_fetch_uses_local_backend_outside_loopback_spa():
    origin = (ROOT / "frontend" / "src" / "apiOrigin.ts").read_text(encoding="utf-8")
    assert "tauri.localhost" in origin
    assert "http://127.0.0.1:4780" in origin
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    assert "from \"./apiOrigin\"" in api
    assert "jarvisApiUrl" in api
    assert api.count("fetch(jarvisApiUrl") >= 10


def test_tauri_shell_attaches_webview_to_backend_origin():
    rust = (ROOT / "frontend" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "http://127.0.0.1:4780/" in rust
    assert "fn attach_portal" in rust
    caps = (ROOT / "frontend" / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8")
    assert "http://127.0.0.1:4780/*" in caps
