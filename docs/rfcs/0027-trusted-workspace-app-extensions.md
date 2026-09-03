# RFC-0027: Trusted workspace app extensions

**Status:** accepted  
**Queue item:** Extensible Agent OS — modular command-center UI  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-03

## Problem

Jarvis Domain Packs can bundle workflows, agents, integrations, metrics, and optional UI defaults, but Jarvis does not yet define a safe extension surface for adding full custom pages, dashboards, or browser-based tools to the universal UI without forking the frontend. OpenHands Agent Canvas v1.16.0 introduced review-first Apps that contribute custom pages while keeping the core application upgradeable. Jarvis needs the same extensibility pattern, but with a stricter trust boundary than OpenHands' current same-browser-context beta.

## Decision

Add a versioned `WorkspaceApp` extension contract. A Workspace App may contribute navigation entries, dashboard pages, project tools, domain views, and tightly scoped actions while remaining separate from Jarvis core.

Each app has a signed/hashed manifest containing app ID, version, source/revision, minimum Jarvis version, contributed routes/pages, requested API capabilities, requested data scopes, network destinations if any, required Domain Packs/integrations, and integrity metadata.

Installation is review-first: newly installed apps are `DISABLED` until the owner reviews the resolved source/revision, manifest, requested capabilities, data access, network access, and contributed UI surfaces. Enabling an app creates an auditable grant that can be revoked independently of uninstalling it.

Unlike the initial OpenHands beta, third-party app code should not receive unrestricted access to the Jarvis browser context. Prefer sandboxed iframe/isolated-webview execution with an explicit message/API bridge. First-party trusted apps may use a less isolated path only when explicitly marked and reviewed. All app calls into Jarvis pass normal identity, capability, policy, audit, rate-limit, and workspace-scope checks.

Domain Packs may declare optional Workspace Apps, but app installation/enabling remains separately reviewable so installing a pack never silently activates executable UI code.

## Acceptance criteria

- [ ] Define a versioned `WorkspaceAppManifest` with ID, version, source/revision, integrity hash/signature metadata, Jarvis compatibility, routes/pages, capabilities, data scopes, network destinations, and dependencies.
- [ ] New apps install disabled by default and show a review screen before enablement.
- [ ] Review shows exact resolved revision/version, source, integrity state, contributed pages, requested Jarvis APIs, data scopes, and external network destinations.
- [ ] Third-party app UI runs in an isolated browser/webview boundary with no direct access to Jarvis auth tokens, DOM, local storage, or unrestricted frontend internals.
- [ ] Apps call Jarvis through a capability-scoped bridge/API; every privileged call is authenticated, authorized, workspace-scoped, and auditable.
- [ ] Apps cannot broaden an Agent Profile, Domain Pack, task, or user policy; effective authority is the intersection of all applicable policies.
- [ ] Per-app grants can be inspected, revoked, disabled, upgraded, and uninstalled independently.
- [ ] App upgrades require manifest/integrity re-evaluation and renewed approval when requested capabilities, data scopes, network destinations, or trust level expand.
- [ ] Domain Packs may reference optional Workspace Apps but cannot silently enable executable app code.
- [ ] One reference app demonstrates a custom operational dashboard reading scoped Jarvis data and invoking one approved action.
- [ ] App failure/crash degrades only that extension and cannot break the core command-center shell.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | workspace-app registry, manifest validation, capability bridge, audit/policy integration |
| Frontend | extension host/router, sandbox bridge, install/review/manage UI |
| Tests | manifest validation, permission isolation, upgrade/revoke, crash isolation |
| Docs | Workspace App authoring/security guide |

## Out of scope

A public app marketplace; arbitrary native-code plugins; replacing Domain Packs; allowing extensions to bypass Jarvis APIs; granting third-party apps unrestricted same-context browser execution by default.

## Notes

Source: https://hub.openhands.dev/blog/new-in-agent-canvas-august-2026 (published 2026-09-02), especially Canvas Apps Beta in OpenHands Agent Canvas v1.16.0.  
Discovery date: 2026-09-03  
Recommendation: ADAPT STRONGLY.  
Jarvis is adapting the upgrade-safe custom-workspace extension model and review-first install flow, while strengthening isolation and preserving Jarvis capability/policy boundaries instead of copying OpenHands' current trusted same-browser-context execution model.
