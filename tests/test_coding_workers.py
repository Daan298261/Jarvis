from dataclasses import replace

from app.agent.coding_workers import (
    ComposerWorker,
    LocalJarvisCodingWorker,
    compact_escalation,
    record_coding_outcome,
    route_coding_task,
    score_complexity,
    worker_stats,
)
from app.hardware import HardwareInfo, detect_hardware
from app.inference.hardware_gate import evaluate_purchase_gate


def test_complexity_keeps_trivial_work_on_deterministic_or_local():
    assert score_complexity("bump version in package.json and run tests") <= 20
    assert score_complexity("rename a helper and update the docstring") <= 40
    assert score_complexity("implement a new distributed scheduler with schema migrations") >= 71


async def test_router_falls_back_when_paid_workers_are_disconnected(jarvis_env):
    decision = await route_coding_task(
        "Implement a multi-file FastAPI feature and add tests for the new router."
    )
    assert decision["complexity"] >= 41
    assert decision["complexity"] <= 70
    assert decision["selected_worker"] == "composer"
    assert decision["execute_worker"] == "local_jarvis"
    assert decision["paid_worker_blocked"] is True
    assert "not connected" in decision["reason"].lower() or "not connected" in str(decision["execute"]["status"])


async def test_historical_local_success_overrides_static_composer(jarvis_env):
    for index in range(4):
        await record_coding_outcome(
            task_id=f"hist-{index}",
            task_class="software engineering",
            worker_id="local_jarvis",
            complexity=50,
            outcome="verified_success",
        )
    decision = await route_coding_task(
        "Add a FastAPI endpoint and a unit test for the existing router.",
        task_class="software engineering",
    )
    assert decision["execute_worker"] == "local_jarvis"
    assert decision["historical"]["override"] is True


async def test_composer_start_does_not_pretend_to_run():
    result = await ComposerWorker().start_task("rewrite the agent loop")
    assert result.success is False
    assert "not connected" in result.errors[0].lower()
    local = await LocalJarvisCodingWorker().start_task("fix a typo")
    assert local.success is True


def test_escalation_package_is_compact():
    package = compact_escalation(
        goal="fix flaky test",
        acceptance_criteria=["pytest passes"],
        task_class="software engineering",
        reason="two local attempts failed",
        attempted_strategies=["retry same patch", "increase timeout"],
        current_diff="diff --git a/x.py",
        failing_tests="FAILED tests/test_x.py",
    )
    text = package.as_prompt_block()
    assert "Escalation package" in text
    assert "two local attempts failed" in text
    assert "full trajectory" in text.lower()


async def test_cost_per_verified_task_metric(jarvis_env):
    await record_coding_outcome(
        task_id="a",
        task_class="software engineering",
        worker_id="composer",
        complexity=50,
        outcome="verified_success",
        estimated_cost_usd=0.40,
    )
    await record_coding_outcome(
        task_id="b",
        task_class="software engineering",
        worker_id="composer",
        complexity=50,
        outcome="failed",
        estimated_cost_usd=0.40,
    )
    stats = {row["worker_id"]: row for row in await worker_stats()}
    assert stats["composer"]["cost_per_verified_task"] == 0.8


def test_hardware_gate_blocks_purchases_without_measurements():
    hw = HardwareInfo(
        os_name="Linux",
        os_version="1",
        architecture="x86_64",
        cpu_name="test",
        cpu_cores=4,
        cpu_threads=8,
        ram_total_gb=16,
        ram_available_gb=12,
        gpu_name=None,
        vram_total_mib=None,
        vram_free_mib=None,
        nvidia_driver=None,
        cuda_version=None,
        disk_free_gb=100,
        disk_total_gb=200,
        python_version="3.12",
        node_installed=True,
        git_installed=True,
        docker_installed=False,
        office_installed=False,
        wsl_available=False,
    )
    gate = evaluate_purchase_gate(hardware=hw, inference_samples=[], agent_results=[])
    assert gate["purchase_allowed"] is False
    assert "Do not buy hardware yet" in gate["recommendation"]
    assert "V100 GPUs" in gate["deferred_until_measured"]


def test_hardware_gate_opens_only_with_enough_samples():
    hw = replace(detect_hardware())
    samples = [
        {"vram_used_mib": 8000, "tokens_per_second": 40, "gpu_layers": "all"}
        for _ in range(3)
    ]
    results = [{"success": True, "profile": "balanced"} for _ in range(5)]
    gate = evaluate_purchase_gate(hardware=hw, inference_samples=samples, agent_results=results)
    assert gate["purchase_allowed"] is True
    assert gate["signals"]["gpu_vram_saturated"] is False
