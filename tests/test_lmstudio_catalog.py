from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.inference.lmstudio_catalog import (
    apply_grade_override,
    build_catalog,
    discover_ggufs,
    fuzzy_match_hint,
    select_catalog_profile,
    set_profile_pinned,
    sort_profiles,
    vram_state_for_weight,
)
from app.inference.runtime_profiles import get_runtime_profile, reset_runtime_profiles
from app.main import app


@pytest.fixture
def catalog_env(jarvis_env, monkeypatch, tmp_path):
    models_root = tmp_path / "lmstudio-models"
    models_root.mkdir()
    monkeypatch.setattr("app.inference.lmstudio_catalog.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.inference.lmstudio_catalog.models_root", lambda: models_root)
    monkeypatch.setattr(
        "app.inference.lmstudio_catalog.default_lmstudio_models_root",
        lambda: models_root,
    )
    monkeypatch.setattr(
        "app.inference.lmstudio_catalog.detect_hardware",
        lambda **kwargs: type(
            "Hw",
            (),
            {"vram_total_mib": 16384},
        )(),
    )
    reset_runtime_profiles()
    return {"tmp": jarvis_env["tmp"], "models_root": models_root}


def _touch_gguf(root: Path, relative: str, size_gb: float) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    with path.open("r+b") as handle:
        handle.truncate(int(size_gb * (1024**3)))
    return path


def test_discover_skips_mmproj_and_non_gguf(catalog_env):
    root = catalog_env["models_root"]
    _touch_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf", 6.1)
    _touch_gguf(root, "nested/mmproj-Qwen3.5-9B.gguf", 0.5)
    (root / "readme.txt").write_text("ignore", encoding="utf-8")

    discovered = discover_ggufs(root)
    names = {item.filename for item in discovered}
    assert "Qwen3.5-9B-Defiant-Q4.gguf" in names
    assert "mmproj-Qwen3.5-9B.gguf" not in names
    assert len(discovered) == 1


def test_fuzzy_match_and_catalog_merge(catalog_env):
    root = catalog_env["models_root"]
    _touch_gguf(root, "Qwen3.8-27B-TurboFCFusion-Q4.gguf", 15.9)
    _touch_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf", 6.1)
    _touch_gguf(root, "unknown-model-Q4.gguf", 4.0)

    assert fuzzy_match_hint("Qwen3.8-27B TurboFCFusion Q4", "Qwen3.8-27B-TurboFCFusion-Q4.gguf")
    catalog = build_catalog(show_hidden=True, root=root)
    assert catalog["catalog_version"] == "2026.09.08"
    assert catalog["vram_gb"] == 16.0
    assert len(catalog["profiles"]) == 8

    best = next(item for item in catalog["profiles"] if item["id"] == "lm-best-overall")
    assert best["matched"] is True
    assert best["quantization"] == "Q4"
    assert best["weight_gb"] == 15.9
    assert best["path"].endswith("Qwen3.8-27B-TurboFCFusion-Q4.gguf")

    assert len(catalog["ungraded"]) == 1
    assert catalog["ungraded"][0]["filename"] == "unknown-model-Q4.gguf"


def test_sort_order_pinned_above_unpinned(catalog_env):
    profiles = [
        {"id": "a", "overall": 9.0, "pinned": False, "favorite": False},
        {"id": "b", "overall": 8.0, "pinned": True, "favorite": False},
        {"id": "c", "overall": 9.5, "pinned": False, "favorite": False},
    ]
    sorted_profiles = sort_profiles(profiles)
    assert [item["id"] for item in sorted_profiles] == ["b", "c", "a"]


def test_vram_hide_and_warn_thresholds():
    assert vram_state_for_weight(10.0) == "ok"
    assert vram_state_for_weight(12.0) == "ok"
    assert vram_state_for_weight(12.1) == "warn"
    assert vram_state_for_weight(16.0) == "warn"
    assert vram_state_for_weight(16.1) == "hidden"


def test_catalog_hides_heavy_models_by_default(catalog_env):
    root = catalog_env["models_root"]
    _touch_gguf(root, "Qwen3.6-40B-Deck-Opus-NEO-CODE-Q4_K_S.gguf", 21.2)

    hidden_default = build_catalog(show_hidden=False, root=root)
    assert all(item["id"] != "lm-coding-heavy" for item in hidden_default["profiles"])

    shown = build_catalog(show_hidden=True, root=root)
    heavy = next(item for item in shown["profiles"] if item["id"] == "lm-coding-heavy")
    assert heavy["vram_state"] == "hidden"


def test_pin_and_override_persistence(catalog_env):
    root = catalog_env["models_root"]
    _touch_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf", 6.1)

    set_profile_pinned("lm-cheap-coding-9b", True)
    catalog = build_catalog(show_hidden=True, root=root)
    cheap = next(item for item in catalog["profiles"] if item["id"] == "lm-cheap-coding-9b")
    assert cheap["pinned"] is True

    updated = apply_grade_override(
        "lm-cheap-coding-9b",
        overall=8.0,
        axes={"coding": 9},
    )
    assert updated["overall"] == 8.0
    assert updated["axes"]["coding"] == 9

    catalog_after = build_catalog(show_hidden=True, root=root)
    cheap_after = next(item for item in catalog_after["profiles"] if item["id"] == "lm-cheap-coding-9b")
    assert cheap_after["overall"] == 8.0
    assert cheap_after["axes"]["coding"] == 9


def test_select_creates_runtime_profile_binding(catalog_env):
    root = catalog_env["models_root"]
    _touch_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf", 6.1)

    runtime = select_catalog_profile("lm-cheap-coding-9b")
    assert runtime["provider"] == "lmstudio"
    assert runtime["privacy_class"] == "local-only"
    assert runtime["is_local"] is True
    assert runtime["model"] == "Qwen3.5-9B-Defiant-Q4"
    assert runtime["quantization"] == "Q4"
    assert "graded-catalog" in runtime["capability_tags"]

    stored = get_runtime_profile(runtime["id"])
    assert stored is not None
    assert stored.provider == "lmstudio"

    catalog = build_catalog(show_hidden=True, root=root)
    cheap = next(item for item in catalog["profiles"] if item["id"] == "lm-cheap-coding-9b")
    assert cheap["runtime_profile_id"] == runtime["id"]

    updated = select_catalog_profile("lm-cheap-coding-9b")
    assert updated["id"] == runtime["id"]


def test_api_endpoints(catalog_env):
    root = catalog_env["models_root"]
    _touch_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf", 6.1)
    _touch_gguf(root, "Qwen3.8-27B-TurboFCFusion-Q4.gguf", 15.9)

    client = TestClient(app)

    catalog = client.get("/api/lmstudio/catalog?show_hidden=false")
    assert catalog.status_code == 200
    body = catalog.json()
    assert "profiles" in body
    assert "ungraded" in body
    assert body["models_root"] == str(root)

    pin = client.post(
        "/api/lmstudio/catalog/lm-cheap-coding-9b/pin",
        json={"pinned": True},
    )
    assert pin.status_code == 200
    assert pin.json() == {"ok": True}

    override = client.post(
        "/api/lmstudio/catalog/lm-cheap-coding-9b/override",
        json={"overall": 7.5, "axes": {"coding": 8}},
    )
    assert override.status_code == 200
    assert override.json()["overall"] == 7.5

    select = client.post("/api/lmstudio/catalog/lm-cheap-coding-9b/select")
    assert select.status_code == 200
    assert select.json()["provider"] == "lmstudio"

    missing = client.post("/api/lmstudio/catalog/lm-coding-heavy/select")
    assert missing.status_code == 404
