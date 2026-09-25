# RFC-0142: Unified capability/plugin SDK, lifecycle and trust

**Status:** accepted  
**Date:** 2026-09-24

## Problem

Tools, modules, skills, connectors, memory providers and UI extensions need one extensibility contract. One-off integrations make parity expensive and increase supply-chain risk.

## Decision

Define a signed Capability Package manifest that can contribute typed tools, MCP/connectors, skills, workflow nodes, memory/retrieval providers, channels, personas and optional UI panels. Lifecycle hooks: discover → verify → install → configure → enable → health → update → disable → uninstall/rollback. Permissions are declarative and least-privilege; package code cannot self-grant permissions.

Support development hot reload only in explicit Developer Mode. Production updates are staged, version-pinned and health-checked with rollback. Third-party packages are quarantined until signature/hash, license, manifest and static policy checks pass. Secrets use Jarvis credential broker references.

## Acceptance criteria

- [ ] Versioned manifest/schema and SDK examples exist.
- [ ] Package types use one lifecycle manager and health/status contract.
- [ ] Declarative filesystem/network/tool/secret permissions are enforced.
- [ ] Signed/hash-pinned install, staged update and rollback work.
- [ ] Dev hot reload cannot be enabled silently in production.
- [ ] UI shows publisher, provenance, license, permissions, health and update state.
- [ ] Existing modules can migrate incrementally without breaking compatibility.

## Likely files

Module manager/registry, `backend/app/capabilities/`, plugin SDK, credential broker, Modules UI, tests.
