"""RFC-0137 Capability Lab registry and deterministic benchmark harness."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.capabilities.registry import get_capability, load_registry
from app.evals.runner import run_capability_tests
from app.main import app


def test_registry_loads_and_has_p0_entries():
    reg = load_registry()
    assert reg.version >= 1
    assert get_capability("reflex_lane_system_one") is not None
    assert get_capability("reflex_browser_computer_use") is not None


def test_registry_api_lists_capabilities():
    client = TestClient(app)
    resp = client.get("/api/capability-lab/registry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total"] >= 5
    ids = {row["id"] for row in body["capabilities"]}
    assert "capability_lab" in ids


def test_benchmark_runs_linked_tests_for_single_capability():
    result = run_capability_tests(["reflex_lane_system_one"])
    assert result["mode"] == "deterministic"
    assert result["ok"] is True


def test_benchmark_api_smoke():
    client = TestClient(app)
    resp = client.post(
        "/api/capability-lab/benchmark",
        json={"capability_ids": ["capability_lab"], "live": False},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_every_linked_test_and_implemented_path_exists():
    """Regression gate: a capability cannot claim tests or code that are not in the tree."""
    from pathlib import Path

    from app.config import repo_root

    root = Path(repo_root())
    for row in load_registry().capabilities:
        for test_id in row.test_ids:
            assert (root / test_id.split("::", 1)[0]).exists(), f"{row.id}: missing {test_id}"
        if row.lifecycle != "specified":
            code_path = row.anzu_path.split(" ", 1)[0]
            assert (root / code_path).exists(), f"{row.id}: missing {code_path}"
        if row.parity_state == "equivalent":
            assert row.peer_evidence and row.test_ids, f"{row.id}: equivalence needs evidence and tests"


def test_runner_ignores_targets_outside_tests_tree():
    from app.evals.runner import _unique_test_paths

    assert _unique_test_paths(["../backend/app/main.py", "--collect-only", "tests/test_owner_intake.py"]) == [
        "tests/test_owner_intake.py"
    ]


def test_live_benchmark_refused_by_default():
    client = TestClient(app)
    resp = client.post("/api/capability-lab/benchmark", json={"live": True})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
