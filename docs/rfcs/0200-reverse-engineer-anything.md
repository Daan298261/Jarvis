# RFC-0200: ANZU Reverse Engineer Anything

**Status:** accepted
**Author:** Codex / Daan
**Date:** 2026-10-05

## Problem

ANZU must investigate a supplied software path and a specific question using real
analysis providers, retain evidence, and explain what is established or unknown.
Registering a skill or connecting an MCP server alone does not meet this requirement.

## Decision

Integrate pinned REA 3.2.1 and its matching skill with task-isolated sessions.
Use a dedicated ANZU-REA WSL2 distribution with Ghidra 12.1.4 and JDK 21 for
native analysis. Source repositories use repository tools. Add JADX for DEX and
Android emulator/ADB observation. Browser observation and static IPA inspection
are included; IPA execution and encrypted-code recovery are not.

Prepare hashed private copies, persist structured evidence, expose managed-task
progress and reports, and require exact-action owner grants before target execution.
Setup and repair must be resumable. Preserve existing user work and inference settings.

## Acceptance criteria

- [ ] Chat requests expose and use reverse_engineer in both agent harnesses.
- [ ] Real PE, .NET, Electron, APK, IPA and browser fixture findings cite evidence.
- [ ] Approved Android emulator captures establish known fixture behavior.
- [ ] Direct/proxy MCP execution cannot bypass approvals.
- [ ] Concurrent targets remain isolated; cancel/restart/change detection work.
- [ ] Reports preserve incomplete coverage and unknowns.
- [ ] Full pytest, frontend lint/build and diff checks pass.
- [ ] Installed ANZU repeats chat-to-report and approval/cleanup acceptance.

## Likely files

Backend investigation service, native tool, routing/harness hooks, policy metadata
and authenticated API; integration settings UI; setup and acceptance scripts;
focused tests and packaged upstream skill/license.

## Out of scope

Promotion to main, public release, automatic feature reconstruction, iOS runtime,
cloud analysis uploads, and changes to protected architecture specifications.

## Notes

Upstream: https://github.com/morluto/rea (MIT).
Windows Ghidra is unavailable upstream; do not claim Windows provider verification
from a package test or a successful MCP handshake.
