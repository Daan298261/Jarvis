from app.inference.agent_bench import AGENT_TASKS, task_catalog, tasks_by_category
from app.inference.harness import benchmark_matrix, harness_status, run_harness


REQUIRED_CATEGORIES = {
    "filesystem",
    "software engineering",
    "shell",
    "browser automation",
    "mixed",
    "multimodal",
    "research",
    "document processing",
    "data processing",
    "long-horizon autonomous",
}


def test_agent_catalog_has_at_least_twenty_realistic_tasks():
    assert len(AGENT_TASKS) >= 20
    catalog = task_catalog()
    assert catalog[0]["id"] == "fs-organize"
    categories = tasks_by_category()
    missing = REQUIRED_CATEGORIES - set(categories)
    assert not missing, missing
    ids = [task.id for task in AGENT_TASKS]
    assert len(ids) == len(set(ids))


def test_benchmark_matrix_covers_models_context_thinking_and_vision():
    matrix = benchmark_matrix()
    assert len(matrix) >= 72
    models = {row.model for row in matrix}
    assert "qwen3.5-9b-abliterated" in models
    assert "qwen3.5-27b" in models
    quants = {row.quant for row in matrix if row.model == "qwen3.5-9b-abliterated"}
    assert "Q8_0" in quants and "Q6_K" in quants
    assert {row.context_size for row in matrix} >= {8192, 16384, 32768}
    assert {row.thinking for row in matrix} == {"off", "selective", "on"}
    assert {row.vision for row in matrix} == {False, True}


def test_dry_run_harness_skips_missing_ggufs_and_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr("app.inference.harness.data_dir", lambda: tmp_path)
    report = run_harness(live=False)
    assert report["agent_catalog_size"] >= 20
    assert report["skipped"] == len(report["configurations"])
    assert report["measured"] == 0
    assert (tmp_path / "benchmarks" / "last-report.json").exists()
    assert (tmp_path / "benchmarks" / "last-report.md").exists()
    markdown = (tmp_path / "benchmarks" / "last-report.md").read_text(encoding="utf-8")
    assert "successful autonomous tasks" in markdown
    status = harness_status()
    assert status["report"]["skipped"] == report["skipped"]
    assert status["matrix_size"] == len(report["configurations"])
