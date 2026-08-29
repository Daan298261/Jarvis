from __future__ import annotations

from pathlib import Path

import pytest


def test_setup_state_persists_and_survives_partial_failure(tmp_path, monkeypatch):
    from app import setup_state as mod

    monkeypatch.setattr(mod, "data_dir", lambda: tmp_path)
    state = mod.save_setup_state({"current_step": "runtime", "inference_choice": "local"})
    assert state["current_step"] == "runtime"
    assert (tmp_path / "setup_state.json").is_file()

    mod.mark_step_complete("welcome", next_step="system")
    mod.mark_step_complete("system", next_step="role")
    again = mod.load_setup_state()
    assert "welcome" in again["completed_steps"]
    assert "system" in again["completed_steps"]
    assert again["inference_choice"] == "local"
    assert again["completed"] is False

    # Failed download should not wipe earlier steps.
    mod.save_setup_state({"last_error": "download failed", "component_status": {"primary_model": {"status": "error"}}})
    recovered = mod.load_setup_state()
    assert recovered["completed_steps"]
    assert recovered["last_error"] == "download failed"
    assert recovered["current_step"] in mod.WIZARD_STEPS


def test_wizard_preset_to_budget_maps_dynamic():
    from app.setup_state import wizard_preset_to_budget

    dyn = wizard_preset_to_budget("dynamic")
    assert dyn["preset"] == "balanced"
    assert dyn["mode"] == "dynamic"
    assert dyn["global_percent"] == 50

    assert wizard_preset_to_budget("minimal")["global_percent"] == 15
    assert wizard_preset_to_budget("maximum")["preset"] == "maximum"
    with pytest.raises(ValueError):
        wizard_preset_to_budget("nope")


def test_complete_setup(tmp_path, monkeypatch):
    from app import setup_state as mod

    monkeypatch.setattr(mod, "data_dir", lambda: tmp_path)
    done = mod.complete_setup()
    assert done["completed"] is True
    assert done["current_step"] == "done"
    assert mod.needs_setup() is False
