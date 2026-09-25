"""Isolated skill evaluation — shadow replay against golden criteria (no production mutation)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .provenance import verify_manifest_integrity
from .schema import DeterministicTest, SkillManifest, SkillStep, VerifierResult
from .store import eval_workspace, utc_now

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class EvaluationError(ValueError):
    pass


def _substitute(value: Any, bindings: dict[str, Any]) -> Any:
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in bindings:
                return match.group(0)
            bound = bindings[name]
            return bound if isinstance(bound, str) else json.dumps(bound, default=str)

        return _PLACEHOLDER.sub(repl, value)
    if isinstance(value, dict):
        return {key: _substitute(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, bindings) for item in value]
    return value


def instantiate_steps(steps: list[SkillStep], bindings: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in steps:
        out.append(
            {
                "tool": step.tool,
                "arguments": _substitute(step.arguments, bindings),
                "description": step.description,
            }
        )
    return out


def _unresolved_placeholders(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(_PLACEHOLDER.findall(value))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(_unresolved_placeholders(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_unresolved_placeholders(item))
    return found


def _run_shadow_replay(
    *,
    workspace: Path,
    steps: list[dict[str, Any]],
    test: DeterministicTest,
) -> dict[str, Any]:
    """Execute a shadow replay that never mutates production state.

    Writes a journal inside the isolated eval workspace only. Tool calls are
    simulated: success is derived from golden criteria and structural checks.
    """
    journal_path = workspace / f"{test.id}.journal.jsonl"
    results: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        unresolved = _unresolved_placeholders(step)
        success = not unresolved
        entry = {
            "index": index,
            "tool": step.get("tool"),
            "arguments": step.get("arguments"),
            "success": success,
            "shadow": True,
            "unresolved": sorted(unresolved),
            "workspace": str(workspace),
        }
        results.append(entry)
        with journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        if not success and test.require_success:
            break

    failures: list[str] = []
    if test.expected_step_count is not None and len(steps) != test.expected_step_count:
        failures.append(
            f"step count {len(steps)} != expected {test.expected_step_count}"
        )
    if test.expected_tools:
        actual_tools = [str(step.get("tool") or "") for step in steps]
        if actual_tools != list(test.expected_tools):
            # Allow prefix match when golden lists unique tool order without duplicates collapsed.
            if actual_tools != test.expected_tools and [
                tool for tool in actual_tools
            ] != test.expected_tools:
                failures.append(f"tool sequence {actual_tools} != {test.expected_tools}")

    for golden in test.golden_outputs:
        if not isinstance(golden, dict):
            continue
        if golden.get("check") == "tools_match_steps":
            step_tools = [str(step.get("tool") or "") for step in steps]
            declared = list(test.expected_tools or [])
            # Compare unique membership — manifest.tools is deduped order of first appearance.
            if declared and sorted(set(step_tools)) != sorted(set(declared)):
                failures.append("tools declared on manifest do not match steps")
            continue
        index = golden.get("index")
        if index is None:
            continue
        if not isinstance(index, int) or index >= len(results):
            failures.append(f"missing golden step index {index}")
            continue
        row = results[index]
        if golden.get("tool") and row.get("tool") != golden.get("tool"):
            failures.append(f"step {index} tool mismatch")
        if golden.get("success") is True and not row.get("success"):
            failures.append(f"step {index} did not succeed in shadow replay")

    if test.require_success and any(not row.get("success") for row in results):
        failures.append("one or more shadow steps failed")

    passed = not failures
    return {
        "test_id": test.id,
        "passed": passed,
        "failures": failures,
        "results": results,
        "journal": str(journal_path),
    }


def evaluate_manifest(
    manifest: SkillManifest,
    *,
    candidate_id: str,
    require_integrity: bool = True,
) -> VerifierResult:
    workspace = eval_workspace(candidate_id)
    marker = workspace / "ISOLATED_EVAL.txt"
    marker.write_text(
        "Skill Forge isolated evaluation workspace.\n"
        "No production paths are mutated by this harness.\n",
        encoding="utf-8",
    )

    details: list[dict[str, Any]] = []
    if require_integrity:
        integrity = verify_manifest_integrity(manifest)
        details.append({"check": "integrity", **integrity})
        if not integrity["valid"]:
            return VerifierResult(
                passed=False,
                tests_run=1,
                tests_passed=0,
                tests_failed=1,
                details=details,
                isolated_workspace=str(workspace),
                evaluated_at=utc_now(),
            )

    tests = list(manifest.tests or [])
    if not tests:
        return VerifierResult(
            passed=False,
            tests_run=0,
            tests_passed=0,
            tests_failed=0,
            details=[{"error": "manifest has no deterministic tests"}],
            isolated_workspace=str(workspace),
            evaluated_at=utc_now(),
        )

    passed_count = 0
    failed_count = 0
    for test in tests:
        if test.id == "manifest_integrity":
            step_tools = [step.tool for step in manifest.steps]
            declared = list(test.expected_tools or [])
            failures: list[str] = []
            if test.expected_step_count is not None and len(manifest.steps) != test.expected_step_count:
                failures.append(
                    f"step count {len(manifest.steps)} != expected {test.expected_step_count}"
                )
            if declared and sorted(set(step_tools)) != sorted(set(declared)):
                failures.append("tools declared on manifest do not match steps")
            result = {
                "test_id": test.id,
                "passed": not failures,
                "failures": failures,
                "results": [{"check": "tools_match_steps", "step_tools": step_tools, "declared": declared}],
            }
            details.append(result)
            if result["passed"]:
                passed_count += 1
            else:
                failed_count += 1
            continue

        steps = instantiate_steps(manifest.steps, test.inputs or {})
        result = _run_shadow_replay(workspace=workspace, steps=steps, test=test)
        details.append(result)
        if result["passed"]:
            passed_count += 1
        else:
            failed_count += 1

    # Ensure eval workspace stays self-contained (no escape markers written elsewhere).
    (workspace / "summary.json").write_text(
        json.dumps(
            {"passed": failed_count == 0, "tests_passed": passed_count, "tests_failed": failed_count},
            indent=2,
        ),
        encoding="utf-8",
    )

    return VerifierResult(
        passed=failed_count == 0 and passed_count > 0,
        tests_run=passed_count + failed_count,
        tests_passed=passed_count,
        tests_failed=failed_count,
        details=details,
        isolated_workspace=str(workspace),
        evaluated_at=utc_now(),
    )
