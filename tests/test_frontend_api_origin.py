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


def test_hud_model_switch_uses_activation_snapshot_and_retries_catalogs():
    apply = (ROOT / "frontend" / "src" / "hud" / "applyRuntimeProfile.ts").read_text(encoding="utf-8")
    selector = (ROOT / "frontend" / "src" / "hud" / "HudModelSelector.tsx").read_text(encoding="utf-8")
    assert "finishModelActivation(result.load)" in apply
    assert "finishModelActivation(runtime.load)" in apply
    assert "Retry local models" in selector
    assert "void refreshProfiles()" in selector


def test_model_play_routes_do_not_block_on_a_second_full_probe():
    runtime_api = (ROOT / "backend" / "app" / "api" / "runtime_profiles.py").read_text(encoding="utf-8")
    catalog_api = (ROOT / "backend" / "app" / "api" / "lmstudio.py").read_text(encoding="utf-8")
    for source in (runtime_api, catalog_api):
        assert "runtime_activation_snapshot()" in source
        assert "force_refresh=True" not in source


def test_tauri_shell_attaches_webview_to_backend_origin():
    rust = (ROOT / "frontend" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "http://127.0.0.1:4780/" in rust
    assert "fn attach_portal" in rust
    caps = (ROOT / "frontend" / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8")
    assert "http://127.0.0.1:4780/*" in caps
