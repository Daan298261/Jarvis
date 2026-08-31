# RFC-0021: Artifact/Crafts output layer

**Status:** accepted  
**Queue item:** Structured artifacts / interactive outputs  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-31

## Problem

Jarvis agents can produce text and tool results, but useful work often needs to become a durable artifact: a diagram, report, dashboard, table, interactive visualization, web component, code bundle, or other structured output. Treating every result as chat text makes outputs harder to inspect, edit, reuse, version, and hand to another agent or workflow.

## Decision

Introduce a first-class `Artifact` abstraction and artifact renderer registry. Agents may emit typed artifact manifests instead of embedding complex output only inside chat.

An artifact has a type, schema/version, title, creator/task lineage, source references, content payload or file references, rendering metadata, permissions, and revision history. The UI renders known artifact types in dedicated viewers/editors while preserving a portable source representation.

Initial artifact types should focus on high-value, deterministic outputs: Markdown/document, table/data, Mermaid/graph diagram, HTML/React preview, JSON/schema object, and file bundle. Artifact rendering must not grant generated code unrestricted access to Jarvis APIs, host files, network, secrets, or browser state.

## Acceptance criteria

- [ ] Persist `Artifact` with type, schema version, title, owner/workspace, creator agent/task, timestamps, provenance/source links, revision ID, and permissions.
- [ ] Artifact registry maps supported types to validation, storage, renderer, export, and edit capabilities.
- [ ] Initial support includes document/Markdown, tabular data, diagram/graph, HTML or React preview, structured JSON, and generic file/bundle artifacts.
- [ ] Agents can return an artifact reference as a task result and other agents/workflows can consume the artifact without reparsing the visible chat transcript.
- [ ] Artifact revisions are immutable/auditable; edits create a new revision while preserving lineage.
- [ ] Users can duplicate, rename, export, attach to a ProjectWorkspace, and pass artifacts into subsequent tasks.
- [ ] Interactive/generated web artifacts render in a sandbox with no implicit access to secrets, host filesystem, Jarvis internal APIs, unrelated workspace state, or unrestricted network calls.
- [ ] Unsupported artifact types degrade to a safe raw/source view rather than failing the task.
- [ ] Artifact provenance identifies inputs and generating task/agent so users can trace how an output was produced.
- [ ] UI separates conversational explanation from the primary artifact while keeping both linked.
- [ ] Tests cover schema validation, revision lineage, permissions, sandbox restrictions, export, and artifact-to-agent handoff.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/artifacts/...`, artifact models/registry/storage |
| Frontend | artifact viewer/editor components and sandboxed preview host |
| Tests | artifact validation, permissions, revision, renderer tests |
| Docs | artifact manifest and renderer extension specification |

## Out of scope

A full office suite, arbitrary native-code execution, or allowing generated frontend code to bypass Jarvis capability policy. Specialized document/spreadsheet/media authoring can build on the artifact contract later.

## Notes

Inspiration: Merlin Crafts and similar chat-to-artifact interfaces. Discovery date: 2026-08-31. Recommendation: **ADAPT**. Jarvis should make artifacts reusable runtime objects, not merely prettier chat messages.
