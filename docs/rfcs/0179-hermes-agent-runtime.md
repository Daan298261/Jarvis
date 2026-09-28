# RFC-0179: Bundle Hermes Agent as an ANZU execution runtime

**Status:** accepted  
**Upstream pin:** NousResearch/hermes-agent `v2026.9.14` at `345cd2b057a452236de401d3534b8502a7465e8d`  
**Date:** 2026-09-25

## Problem

ANZU has durable task execution, tools, MCP and agent rooms, but no selectable adapter for the Hermes Agent harness. Bundling Hermes without an explicit boundary could create a second authority path around ANZU approvals, audit, model selection and task cancellation.

## Decision

Bundle NousResearch Hermes Agent as an optional, version-pinned managed runtime and connect it to ANZU through its ACP interface. Keep its source and Python environment isolated from ANZU's backend dependencies. ANZU owns the task, selected runtime profile, resource budget, policy, approvals, persistence, user-facing progress and cancellation.

Hermes must use the task's selected ANZU model endpoint/profile. Expose ANZU capabilities only through task-scoped, policy-enforced tools. Disable direct Hermes terminal, filesystem, network and browser tools unless each action can be mediated by the matching ANZU policy and approval path. An ACP permission request may narrow ANZU authority but never grant more authority. Fail closed when the bridge or policy check is unavailable.

The runtime is opt-in, independently installable/updateable, pinned to a reviewed upstream release/commit, and accompanied by upstream license and dependency provenance. Do not run a floating installer or install dependencies into ANZU's Python environment. The initial version targets the Windows desktop app; unsupported platform behavior is explicit.

## Acceptance criteria

- [ ] Settings can install, verify, launch, stop and remove the pinned Hermes runtime without changing ANZU's Python environment; version/hash and health are visible.
- [ ] A user can select Hermes for an ANZU task and the selected ANZU model/runtime profile is used without copying credentials into command arguments, logs or persisted task text.
- [ ] Hermes work is bound to the existing durable ANZU task/goal, emits normalized progress/tool events, and supports cancellation, failure recovery and replay.
- [ ] Hermes can act only through task-scoped ANZU tools; all side effects use ANZU authorization, approval, budget, audit and path/network restrictions.
- [ ] Hermes cannot silently fall back to its own credentials, model, unmediated tools or an alternate endpoint when the ANZU profile/bridge is unavailable.
- [ ] Fresh-install and upgrade tests cover supported Windows packaging, offline/unavailable upstream behavior, runtime integrity and rollback; no upstream code is loaded into ANZU's global environment.
- [ ] Upstream MIT notice and a release SBOM/provenance record are included with the bundled runtime.
- [ ] Unit and integration tests cover ACP transport, model/profile propagation, tool authorization, fail-closed behavior, event mapping and cancellation.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/`, `backend/app/api/`, runtime settings and task/goal services |
| Frontend | Settings runtime controls, task engine selector and progress surface |
| Installer | `installer/windows/` managed-runtime staging and manifest |
| Tests | ACP/runtime manager, policy integration, task lifecycle and installer checks |
| Docs | `docs/rfcs/0179-hermes-agent-runtime.md`, dependency notice/provenance |

## Out of scope

Replacing ANZU's native agent loop, moving ANZU-owned task state or credentials into Hermes, Hermes messaging gateways/cron/desktop UI, unrestricted Hermes built-in tools, automatic upstream updates, or changing the model stack.

## Notes

Upstream project: <https://github.com/NousResearch/hermes-agent>. The v2026.9.14 tag resolves to the immutable commit above; its `pyproject.toml` declares Python `>=3.11,<3.14`, an `acp` extra, and MIT. Upstream documents ACP as JSON-RPC over stdio and notes that it does not publish a supported wheel for ordinary `pip` installation. Keep its source checkout and environment isolated from ANZU's backend.
