"""RFC-0138 custom presence backend (Phases A, B, D)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.inference.manager import MANAGER
from app.persona.named_persona import apply_main_persona
from app.persona.session_personality import set_active_mode
from app.presence.custom_ui import (
    ORB_CONSTRAINT,
    preview_shape_id,
    reapply_stored_custom_presence,
    reset_registered_shapes_for_tests,
    resolve_presence_shape_id,
    validate_orb_composition,
)
from app.providers.base import ChatMessage, ChatResult

VALID_COMPOSITION = {
    "version": 1,
    "orb_color": "#9B1B30",
    "accent_color": "#D4A017",
    "framing": {"yaw": 0.08, "position": [0, 0.06, 0]},
    "layers": [
        {
            "kind": "sphere",
            "count_scale": 1.0,
            "radius": 0.78,
            "y": 0.12,
            "gold": 0.15,
            "light": 1.35,
            "flow": 0.4,
            "size": 1.35,
            "motion": "breathe",
        }
    ],
}


@pytest.fixture
def presence_box(monkeypatch, tmp_path):
    reset_registered_shapes_for_tests()
    box = {"settings": AppSettings(allowed_directories=[str(tmp_path)])}
    monkeypatch.setattr("app.config.settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.config.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.config.save_settings", lambda updated: box.__setitem__("settings", updated))
    monkeypatch.setattr("app.presence.custom_ui.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.presence.custom_ui.save_settings", lambda updated: box.__setitem__("settings", updated))
    monkeypatch.setattr("app.presence.custom_ui.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.persona.named_persona.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.persona.named_persona.save_settings", lambda updated: box.__setitem__("settings", updated))
    monkeypatch.setattr("app.persona.session_personality.load_settings", lambda: box["settings"])
    monkeypatch.setattr("app.persona.session_personality.save_settings", lambda updated: box.__setitem__("settings", updated))
    yield box
    reset_registered_shapes_for_tests()
    MANAGER.provider = None
    MANAGER.state.loaded = False
    MANAGER.state.vision_loaded = False


@pytest.fixture
def api_client(presence_box, allow_loopback_api):
    from app.main import app

    return TestClient(app)


def test_validator_accepts_allowed_kinds():
    assert validate_orb_composition(VALID_COMPOSITION) == []
    for kind in ("ring", "arc", "orbit", "sparks"):
        comp = json.loads(json.dumps(VALID_COMPOSITION))
        comp["layers"] = [{"kind": kind, "motion": "static"}]
        assert validate_orb_composition(comp) == []
    sample = json.loads(json.dumps(VALID_COMPOSITION))
    sample["layers"] = [{"kind": "shape_sample", "shape_id": "stormbird", "motion": "pulse"}]
    assert validate_orb_composition(sample) == []


def test_validator_rejects_forbidden_and_unknown():
    for token in ("mesh", "gltf", "glb", "texture", "html", "css"):
        bad = json.loads(json.dumps(VALID_COMPOSITION))
        bad["layers"] = [{"kind": token, "motion": "static"}]
        assert validate_orb_composition(bad)
    custom = json.loads(json.dumps(VALID_COMPOSITION))
    custom["layers"] = [{"kind": "shape_sample", "shape_id": "custom_ui_cui_abc", "motion": "static"}]
    assert validate_orb_composition(custom)
    unknown = json.loads(json.dumps(VALID_COMPOSITION))
    unknown["layers"] = [{"kind": "not_real", "motion": "static"}]
    assert validate_orb_composition(unknown)


def test_resolve_presence_shape_id_hexstrike_wins():
    assert resolve_presence_shape_id(True, "custom_ui_cui_aaa", "stormbird") == "hex_aegis"
    assert resolve_presence_shape_id(False, "custom_ui_cui_aaa", "ocean_swell") == "custom_ui_cui_aaa"
    assert resolve_presence_shape_id(False, "", "ocean_swell") == "ocean_swell"


def _messages_contain_constraint(messages: list[ChatMessage]) -> bool:
    for message in messages:
        content = message.content
        if isinstance(content, str) and ORB_CONSTRAINT in content:
            return True
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and ORB_CONSTRAINT in str(part.get("text", "")):
                    return True
    return False


class ScriptedProvider:
    def __init__(self, responses: list[str], *, fail_unavailable: bool = False):
        self.responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.fail_unavailable = fail_unavailable

    async def chat(self, messages, **kwargs):
        self.calls.append(list(messages))
        if self.fail_unavailable:
            raise RuntimeError("down")
        if not self.responses:
            raise RuntimeError("no response")
        text = self.responses.pop(0)
        return ChatResult(content=text)


@pytest.mark.asyncio
async def test_job_injects_constraint_on_every_call(presence_box):
    provider = ScriptedProvider([json.dumps(VALID_COMPOSITION)])
    MANAGER.provider = provider
    MANAGER.state.loaded = True
    MANAGER.state.vision_loaded = False
    from app.presence.custom_ui import run_custom_presence_job

    job = await run_custom_presence_job(prompt_text="ember halo", image_bytes=None, image_filename="", image_content_type="")
    assert job.status == "succeeded"
    assert _messages_contain_constraint(provider.calls[0])


@pytest.mark.asyncio
async def test_scripted_success_registers_preview(presence_box):
    provider = ScriptedProvider([json.dumps(VALID_COMPOSITION)])
    MANAGER.provider = provider
    MANAGER.state.loaded = True
    from app.presence.custom_ui import get_registered_shape, run_custom_presence_job

    job = await run_custom_presence_job(prompt_text="halo", image_bytes=None, image_filename="", image_content_type="")
    assert job.status == "succeeded"
    assert job.preview_shape_id == preview_shape_id(job.id)
    assert get_registered_shape(job.preview_shape_id) is not None
    assert validate_orb_composition(job.orb_composition or []) == []


@pytest.mark.asyncio
async def test_mesh_payload_rejected_after_regenerate(presence_box):
    mesh = json.dumps({"version": 1, "orb_color": "#111111", "accent_color": "#222222", "framing": {"yaw": 0, "position": [0, 0, 0]}, "layers": [{"kind": "mesh"}]})
    provider = ScriptedProvider([mesh, mesh])
    MANAGER.provider = provider
    MANAGER.state.loaded = True
    from app.presence.custom_ui import run_custom_presence_job

    job = await run_custom_presence_job(prompt_text="bad", image_bytes=None, image_filename="", image_content_type="")
    assert job.status == "rejected"
    assert job.error and job.error["code"] == "constraint_rejected"
    assert len(provider.calls) == 2
    for call in provider.calls:
        assert _messages_contain_constraint(call)


@pytest.mark.asyncio
async def test_model_unavailable_fail_closed(presence_box):
    MANAGER.provider = None
    MANAGER.state.loaded = False
    from app.presence.custom_ui import run_custom_presence_job

    job = await run_custom_presence_job(prompt_text="x", image_bytes=None, image_filename="", image_content_type="")
    assert job.status == "failed"
    assert job.error and job.error["code"] == "model_unavailable"
    assert job.orb_composition is None


@pytest.mark.asyncio
async def test_vision_unavailable_does_not_call_model(presence_box):
    provider = ScriptedProvider([json.dumps(VALID_COMPOSITION)])
    MANAGER.provider = provider
    MANAGER.state.loaded = True
    MANAGER.state.vision_loaded = False
    from app.presence.custom_ui import run_custom_presence_job

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    job = await run_custom_presence_job(
        prompt_text="",
        image_bytes=png,
        image_filename="x.png",
        image_content_type="image/png",
    )
    assert job.status == "failed"
    assert job.error and job.error["code"] == "vision_unavailable"
    assert provider.calls == []


def test_set_default_persists_and_reapply(presence_box, api_client):
    provider = ScriptedProvider([json.dumps(VALID_COMPOSITION)])
    MANAGER.provider = provider
    MANAGER.state.loaded = True
    resp = api_client.post("/api/custom-presence/jobs", json={"prompt_text": "golden ring"})
    assert resp.status_code == 200
    job = resp.json()
    assert job["status"] == "succeeded"
    save = api_client.post(
        "/api/custom-presence/presets",
        json={"job_id": job["id"], "name": "My look", "set_default": True},
    )
    assert save.status_code == 200
    body = save.json()
    assert sum(1 for row in body["presets"] if row["default"]) == 1
    preset_id = body["default_preset_id"]
    assert preset_id
    box = presence_box
    reloaded = AppSettings.model_validate(box["settings"].model_dump())
    assert reloaded.custom_presence.default_preset_id == preset_id
    box["settings"].custom_presence.active_preset_id = ""
    reapply_stored_custom_presence()
    assert box["settings"].custom_presence.active_preset_id == preset_id


def test_named_personas_put_keeps_active_preset(presence_box, monkeypatch):
    box = presence_box
    box["settings"].custom_presence.active_preset_id = "cui_deadbeefdead"
    box["settings"].custom_presence.presets = {}
    calls: list[str] = []

    def fake_set(profile_id: str):
        calls.append(profile_id)
        return type("Item", (), {"id": profile_id})()

    monkeypatch.setattr("app.persona.named_persona.set_active_voice_profile_id", fake_set)
    monkeypatch.setattr(
        "app.persona.named_persona.pack_status",
        lambda _pid: "ok",
    )
    apply_main_persona("aegir")
    assert box["settings"].custom_presence.active_preset_id == "cui_deadbeefdead"


def test_session_personality_does_not_touch_custom_presence(presence_box):
    box = presence_box
    box["settings"].custom_presence.default_preset_id = "cui_abcabcabcabc"
    before = box["settings"].custom_presence.model_dump()
    set_active_mode("coding")
    after = box["settings"].custom_presence.model_dump()
    assert before == after


def test_api_routes_registered():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/custom-presence/jobs" in paths
    assert "/api/custom-presence/jobs/{job_id}" in paths
