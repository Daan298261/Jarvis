import json
import os
from pathlib import Path
import subprocess

import pytest

from app.inference.default_candidates import list_model_candidates


def test_lightweight_candidates_have_verified_public_artifacts():
    candidates = [c for c in list_model_candidates() if c.verified_at == "2026-10-28"]
    assert len(candidates) == 4
    for candidate in candidates:
        assert candidate.weight_gb < 3
        assert candidate.uncensored and candidate.license_id == "apache-2.0"
        assert len(candidate.revision) == 40 and len(candidate.sha256) == 64
        assert candidate.filename.endswith(".gguf")
        assert candidate.benchmark_required and not candidate.recommended
    seed = json.loads(Path("backend/app/inference/lmstudio_graded_profiles.json").read_text())
    rows = {row["id"]: row for row in seed["profiles"]}
    for candidate in candidates:
        row = rows["lm-" + candidate.key]
        assert row["huggingface"]["sha256"] == candidate.sha256
        assert row["overall"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows bootstrap execution")
def test_upgrade_bootstrap_reuses_components():
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", "tests/windows/model-upgrade-reuse.ps1"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
