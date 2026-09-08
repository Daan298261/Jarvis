from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.inference.lmstudio_catalog import (
    build_catalog,
    discover_ggufs,
    discovery_payload,
    select_catalog_profile,
    set_profile_override,
    set_profile_pin,
    sort_profiles,
    vram_state_for_weight,
)
from app.inference.runtime_profiles import get_runtime_profile, reset_runtime_profiles
from app.main import app


@pytest.fixture
def catalog_env(tmp_path, monkeypatch):
    models_root = tmp_path / "lmstudio-models"
    models_root.mkdir()
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: tmp_path)
    reset_runtime_profiles()
    return {"tmp": tmp_path, "models_root": models_root}


def _write_gguf(root: Path, name: str, weight_gb: float = 0.001) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * max(1, int(weight_gb * (1024**3))))
    return path


def _patch_weights(monkeypatch, weights: dict[str, float]):
    def fake_weight(path: Path) -> float:
        for key, value in weights.items():
            if key in path.name:
                return value
        return round(path.stat().st_size / (1024**3), 1)

    monkeypatch.setattr("app.inference.lmstudio_catalog.file_weight_gb", fake_weight)


def test_discover_skips_mmproj_and_non_gguf(catalog_env):
    root = catalog_env["models_root"]
    _write_gguf(root, "Qwen3.8-27B-TurboFCFusion-Q4.gguf", 0.01)
    _write_gguf(root, "mmproj-Qwen3.8-27B.gguf", 0.01)
    (root / "readme.txt").write_text("not a model", encoding="utf-8")

    found = discover_ggufs(root)
    names = {item.filename for item in found}
    assert "Qwen3.8-27B-TurboFCFusion-Q4.gguf" in names
    assert "mmproj-Qwen3.8-27B.gguf" not in names
    assert len(found) == 1


def test_vram_state_thresholds():
    assert vram_state_for_weight(10.0) == "ok"
    assert vram_state_for_weight(12.0) == "warn"
    assert vram_state_for_weight(15.9) == "warn"
    assert vram_state_for_weight(16.1) == "hidden"
    assert vram_state_for_weight(21.2) == "hidden"


def test_catalog_merge_match_sort_and_hide(catalog_env, monkeypatch):
    root = catalog_env["models_root"]
    _write_gguf(root, "Qwen3.8-27B-TurboFCFusion-Q4.gguf")
    _write_gguf(root, "Qwen3.6-40B-Deck-Opus-NEO-CODE-Q4_K_S.gguf")
    _write_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf")
    _write_gguf(root, "random-ungraded-model-Q4.gguf")
    _patch_weights(
        monkeypatch,
        {
            "TurboFCFusion": 15.9,
            "NEO-CODE": 21.2,
            "Defiant": 6.1,
            "random-ungraded": 4.4,
        },
    )

    catalog = build_catalog(show_hidden=False, models_root=root)
    ids = [profile["id"] for profile in catalog["profiles"]]
    assert "lm-best-overall" in ids
    assert "lm-coding-heavy" not in ids
    assert catalog["ungraded"]
    assert any(item["filename"] == "random-ungraded-model-Q4.gguf" for item in catalog["ungraded"])

    best = next(p for p in catalog["profiles"] if p["id"] == "lm-best-overall")
    assert best["matched"] is True
    assert best["vram_state"] == "warn"
    assert best["path"].endswith("Qwen3.8-27B-TurboFCFusion-Q4.gguf")

    with_hidden = build_catalog(show_hidden=True, models_root=root)
    assert any(p["id"] == "lm-coding-heavy" for p in with_hidden["profiles"])


def test_sort_prefers_pinned_then_overall():
    rows = [
        {"id": "a", "display_name": "A", "overall": 9.0, "pinned": False, "favorite": False},
        {"id": "b", "display_name": "B", "overall": 8.0, "pinned": True, "favorite": False},
        {"id": "c", "display_name": "C", "overall": 9.5, "pinned": False, "favorite": False},
    ]
    sorted_rows = sort_profiles(rows)
    assert [row["id"] for row in sorted_rows] == ["b", "c", "a"]


def test_pin_and_override_persist(catalog_env):
    root = catalog_env["models_root"]
    _write_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf", 0.006)

    set_profile_pin("lm-cheap-coding-9b", True)
    updated = set_profile_override(
        "lm-cheap-coding-9b",
        overall=7.9,
        axes={"coding": 9},
    )
    assert updated["pinned"] is True
    assert updated["overall"] == 7.9
    assert updated["axes"]["coding"] == 9

    catalog = build_catalog(show_hidden=True, models_root=root)
    cheap = next(p for p in catalog["profiles"] if p["id"] == "lm-cheap-coding-9b")
    assert cheap["pinned"] is True
    assert cheap["overall"] == 7.9
    assert cheap["axes"]["coding"] == 9


def test_select_creates_lmstudio_runtime_profile(catalog_env):
    root = catalog_env["models_root"]
    _write_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf", 0.006)

    profile = select_catalog_profile("lm-cheap-coding-9b", models_root=root)
    assert profile.provider == "lmstudio"
    assert profile.privacy_class == "local-only"
    assert profile.is_local is True
    assert profile.model == "Qwen3.5-9B-Defiant-Q4"
    assert profile.quantization == "Q4"
    assert "graded-catalog" in profile.capability_tags

    catalog = build_catalog(show_hidden=True, models_root=root)
    cheap = next(p for p in catalog["profiles"] if p["id"] == "lm-cheap-coding-9b")
    assert cheap["runtime_profile_id"] == profile.id

    rebound = select_catalog_profile("lm-cheap-coding-9b", models_root=root)
    assert rebound.id == profile.id
    stored = get_runtime_profile(profile.id)
    assert stored is not None
    assert stored.provider == "lmstudio"


def test_api_endpoints(catalog_env, monkeypatch):
    root = catalog_env["models_root"]
    _write_gguf(root, "Qwen3.5-9B-Defiant-Q4.gguf")
    _write_gguf(root, "Qwen3.6-40B-Deck-Opus-NEO-CODE-Q4_K_S.gguf")
    _patch_weights(monkeypatch, {"Defiant": 6.1, "NEO-CODE": 21.2})

    monkeypatch.setattr(
        "app.inference.lmstudio_catalog.resolve_models_root",
        lambda: root,
    )
    client = TestClient(app)

    catalog = client.get("/api/lmstudio/catalog?show_hidden=false")
    assert catalog.status_code == 200
    body = catalog.json()
    assert "catalog_version" in body
    assert body["models_root"] == str(root)
    assert isinstance(body["profiles"], list)
    assert isinstance(body["ungraded"], list)

    pin = client.post("/api/lmstudio/catalog/lm-cheap-coding-9b/pin", json={"pinned": True})
    assert pin.status_code == 200
    assert pin.json() == {"ok": True}

    override = client.post(
        "/api/lmstudio/catalog/lm-cheap-coding-9b/override",
        json={"overall": 7.5, "axes": {"speed_cost": 10}},
    )
    assert override.status_code == 200
    assert override.json()["overall"] == 7.5
    assert override.json()["axes"]["speed_cost"] == 10

    select = client.post("/api/lmstudio/catalog/lm-cheap-coding-9b/select")
    assert select.status_code == 200
    runtime = select.json()
    assert runtime["provider"] == "lmstudio"
    assert runtime["privacy_class"] == "local-only"

    discovery = client.get("/api/lmstudio/discovery")
    assert discovery.status_code == 200
    assert discovery.json()["count"] >= 2


def test_discovery_payload_lists_models(catalog_env):
    root = catalog_env["models_root"]
    _write_gguf(root, "nested/Qwen3.5-9B-Defiant-Q4.gguf", 0.006)
    payload = discovery_payload(models_root=root)
    assert payload["count"] == 1
    assert payload["models"][0]["filename"] == "Qwen3.5-9B-Defiant-Q4.gguf"
