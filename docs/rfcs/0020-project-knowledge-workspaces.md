# RFC-0020: Persistent project knowledge workspaces

**Status:** accepted  
**Queue item:** Persistent project knowledge / reusable context  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-31

## Problem

Jarvis can persist agents and memories, but reusable project-scoped knowledge needs a clearer product abstraction. Users should be able to attach files, URLs, notes, repositories, media transcripts, and generated artifacts to a project once and have relevant agents reuse that knowledge without repeatedly uploading or pasting the same sources.

## Decision

Add a first-class `ProjectWorkspace` knowledge boundary. A workspace owns project metadata, members/agents, source references, indexed chunks, source provenance, retention policy, permissions, and generated artifacts.

Sources are ingested through typed adapters rather than flattened into one prompt. Retrieval is scoped by workspace, policy, source trust, freshness, and task relevance. Agents may have access to multiple workspaces, but context must never cross workspace boundaries unless an explicit relationship or user action allows it.

Knowledge storage is distinct from user/global memory: project sources are evidentiary/project material; memory captures learned preferences/state. Agents must preserve source provenance so answers and downstream tasks can cite or inspect the originating material.

## Acceptance criteria

- [ ] Persist `ProjectWorkspace` with name, description, owners/members, allowed agents, retention policy, privacy class, and source collection.
- [ ] Workspace sources support at minimum local files, URLs, plain notes/text, and existing Jarvis artifacts; adapters are extensible for repositories, transcripts, cloud drives, and other source types.
- [ ] Each source records canonical identity, ingestion time, last refresh/check time, content hash/version, trust metadata, and provenance.
- [ ] Re-ingestion deduplicates unchanged sources and versions changed sources rather than silently overwriting provenance.
- [ ] Retrieval is workspace-scoped by default and cannot leak chunks from unrelated workspaces.
- [ ] Agents can be granted read, contribute, or manage access to a workspace separately from their global capabilities.
- [ ] Users can mark sources as authoritative, reference-only, untrusted, or excluded from autonomous action decisions.
- [ ] Large sources are indexed/retrieved selectively rather than injected into every model call.
- [ ] Generated outputs can be saved back to the workspace with parent-source/task lineage.
- [ ] Workspace UI shows sources, status/freshness, recent outputs, associated agents/workflows, and effective permissions.
- [ ] Deleting a source removes it from future retrieval and handles derived indexes according to retention/audit policy.
- [ ] Tests cover isolation, dedup/versioning, permission denial, stale-source refresh, provenance, deletion, and multi-agent access.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/knowledge/...`, workspace/source models, retrieval service |
| Frontend | project/workspace source manager and provenance views |
| Tests | workspace isolation, ingestion, retrieval, permissions |
| Docs | project knowledge model and source adapter contract |

## Out of scope

Global autobiographical/user memory, Domain Pack packaging itself, and unrestricted crawling of linked websites. Domain Packs may instantiate ProjectWorkspaces but do not replace this runtime abstraction.

## Notes

Inspiration: Merlin Projects/knowledge bases, adapted to Jarvis's multi-agent and policy architecture. Discovery date: 2026-08-31. Recommendation: **ADAPT**. This complements RFC-0007 Domain/workspace packs: packs define reusable configuration; `ProjectWorkspace` holds a live project's actual knowledge and artifacts.
