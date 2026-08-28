# RFC-0007: Domain/workspace packs

**Status:** accepted  
**Queue item:** Specialist packs / reusable domains  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Manually creating many agents, workflows, policies, integrations, and knowledge stores does not scale and makes Jarvis installations hard to reproduce or share.

## Decision

Introduce installable Domain Packs that declaratively bundle goals, policies, Agent Profiles, workflows, knowledge/index definitions, integration requirements, metrics, and optional UI defaults. Packs are versioned, inspectable, and user-owned.

A pack may instantiate a complete workspace such as Publishing, Software Company, Household, Security, or Research without hard-coding those domains into Jarvis core.

## Acceptance criteria

- [ ] Define a versioned pack manifest/schema.
- [ ] Pack installation previews every created/changed resource before apply.
- [ ] Packs can declare dependencies and minimum Jarvis version.
- [ ] User modifications survive pack upgrades through explicit merge/override semantics.
- [ ] Pack code/tools are subject to signature/trust and capability policy.
- [ ] Export supports user-created packs with secrets excluded.
- [ ] Tests cover install, upgrade, conflict, rollback, and uninstall.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | pack manager, schemas, migrations |
| Frontend | pack install/manage UI |
| Tests | pack lifecycle tests |
| Docs | pack authoring specification |

## Out of scope

A public commercial marketplace; this RFC only creates the pack format/runtime.

## Notes

Inspiration: FounderOS encoded-company/workspace concept and Zoey marketplace direction. Recommendation: ADAPT STRONGLY.
