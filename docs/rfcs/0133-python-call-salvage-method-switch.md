# RFC-0133: Salvage python tool calls and method-switch on failure

**Status:** implemented  
**Queue item:** Tool reliability — copy/script failures should not stall on malformed python calls  
**Author:** Cursor session (Taco 1.4.9 log)  
**Date:** 2026-09-22

## Problem

On 1.4.9 the owner asked Jarvis to copy license-manager source into `Documents\jarvis-test`. The python tool failed with `Unknown action run_code>\nimport os…` because Qwen stuffed the script into `action`. A later `run_file` used a relative `snapshot_repo.py` that resolved under `%LOCALAPPDATA%\Jarvis`. Recovery required two different tools and three failures before Expert 27B, so the worker repeated python instead of `filesystem copy` or computer-use.

## Decision

1. Salvage python arguments: if `action` starts with `run_code>` plus source, treat as `run_code`/`code`. Resolve `run_file` against `working_directory`; error with filesystem-copy guidance when the script is missing.
2. Recovery: after python failure, prefer filesystem copy, then terminal, then screenshot/desktop/cua.
3. Escalate after two consecutive failures when the kinds include usage/not_found, or after three failures. If Expert 27B cannot load, inject a canned method-switch plan that includes vision/computer-use as last resort.

Do not put License Manager source in this public git tree.

## Acceptance criteria

- [x] `normalize_python_call` recovers the live 1.4.9 `run_code>` blob
- [x] Relative `run_file` missing scripts fail with copy guidance
- [x] `should_escalate` fires on two usage/not_found failures
- [x] Canned plan names filesystem copy then screenshot/desktop
- [x] `python -m pytest` for the new/updated tests

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tools/python_exec.py`, `backend/app/agent/recovery.py`, `backend/app/agent/escalation.py`, `backend/app/agent/loop.py` |
| Tests | `tests/test_python_call_normalize.py`, `tests/test_escalation.py`, `tests/test_recovery.py` |

## Out of scope

Committing `tools/license_manager/`; live 27B hotswap on the cloud VM.

## Implementation note

Already on `development` tip inside #366 @ `ba12c618` (no dedicated 0133 PR; salvage shipped with that HexStrike/MCP land): `normalize_python_call`, python recovery that prefers filesystem copy, `should_escalate` on two usage/not_found failures, and `canned_method_switch_plan`. 33 tests across `tests/test_python_call_normalize.py`, `tests/test_recovery.py` (including parametrized classification), and `tests/test_escalation.py`. Live 27B hotswap remains desktop sign-off.
