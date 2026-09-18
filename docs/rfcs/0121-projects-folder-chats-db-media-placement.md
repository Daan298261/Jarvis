# RFC-0121: Projects folder, chats in DB, media placement

**Status:** accepted  
**Queue item:** Persistent project knowledge / reusable context (extends RFC-0020; no new §58 checkbox)  
**Author:** Jarvis Architect  
**Date:** 2026-09-18

**Parent / index:** [RFC-0118](0118-taco-goals-highest-leverage.md) rank 4 (Taco goal 4).  
**Related (do not rewrite):** [RFC-0020](0020-project-knowledge-workspaces.md) (`accepted` — knowledge retrieval; **this** RFC owns folder + chat + blob topology). [RFC-0109](0109-media-file-video-upload-phone-and-pc.md) ingest. [RFC-0021](0021-artifact-crafts-output-layer.md) artifacts. [RFC-0011](0011-memory-context-repositories-consolidation.md) structured memory. [`SWARM_ARCHITECTURE.md`](../../SWARM_ARCHITECTURE.md) §2 Database Node vs Storage Node. [`PORTAL_UX.md`](../../PORTAL_UX.md) left-rail Projects (today: portal-local `localStorage` — **this RFC supersedes that storage rule**; Architect updates PORTAL_UX after accept). RFC-0108: phone is not a second memory authority.

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail**.

## Problem

Taco wants **projects as a real folder structure**, **chats in the internal database**, and **media on disk** next to the DB-host when that is the same PC, otherwise on a **storage node**.

Today:

- Left-rail Projects persist in **browser `localStorage`** (`frontend/src/projects.ts`) as name + task id lists. Clearing the origin, another browser, or the phone loses grouping.
- `conversations` already exist in SQLite (`backend/app/db/models.py`) but are not first-class project members.
- RFC-0020 specifies `ProjectWorkspace` knowledge (sources, chunks, provenance) and does **not** specify on-disk layout, chat rows, or media colocation vs storage node.
- RFC-0109 will ingest media into an artifact store; without this RFC, implementers can dump blobs into SQLite, leave them only on the phone, or pick an ad-hoc path that ignores swarm topology.

Portal-only projects are a **fail**. Chats as Markdown files that bypass the internal DB are a **fail**. Media bytes stored only in chat JSON are a **fail**.

## Decision

Make **Project** a Leader-owned record. Chats live in the **internal DB**. Media bytes live on a **disk path**: colocated with the DB-host node when that is the same PC; otherwise on the swarm **Storage Node**. RFC-0020 workspaces attach to the same project id; they do not replace this layout.

### 1. Folder layout (DB-host or storage node)

Canonical tree under the Jarvis data directory **on the node that owns the files**:

```text
<data>/
  jarvis.db                      # internal DB (chats, project rows, media metadata)
  projects/
    <project_id>/
      media/                     # RFC-0109 / 0021 bytes
      artifacts/                 # optional non-media artifact files
```

Owner-visible names map to `project_id` in the DB (stable id; rename does not rewrite history). Optional human `README.md` / Obsidian vault notes (RFC-0107) may **link** a project; they are not the chat store.

Single-PC (today’s default): the Leader PC **is** the DB-host; media directories live on that same disk tree. Do not require a second machine.

### 2. Chats in the internal DB

- Project membership, titles, and conversation/task links persist in SQLite (or the current internal DB), **not** in `localStorage` and **not** as the source of truth in project folders.
- Each owner chat/turn that belongs to a project stores `project_id` on the conversation (and task when a managed task exists).
- Phone companion chats **sync into the same tables** (RFC-0108 / existing companion sync). The phone may cache a snapshot; the Leader DB is canonical when reachable.
- Deleting a project is a policy-gated operation: conversations remain queryable per retention rules; media files follow the same retention. Silent orphaning of blobs is a fail.

Migrate existing `localStorage` project groupings into DB rows on first Leader load after this lands (best-effort; do not destroy ungrouped recents).

### 3. Media placement

| Situation | Bytes live | DB holds |
| --- | --- | --- |
| Same PC as DB-host node (default) | `<data>/projects/<id>/media/…` on that PC | artifact id, kind, hash, size, relative path, `node_id` = DB-host |
| DB-host and file PC differ (swarm) | Storage Node disk under the same relative layout | artifact id, kind, hash, size, **storage node id + path**; DB does not inline file bytes |

RFC-0109 ingest **must** write through this placement (one artifact id space). Analyze/OCR reads the file from that path (or storage-node fetch). Companion uploads go to the Leader; they do not remain the canonical copy on the phone.

If the storage node is unreachable, upload **fails with a clear error** or queues with Outbox-class persistence — it does not pretend the artifact is stored. Empty path / missing file at analyze time is a hard error, not a silent describe-from-filename.

**Will not:** put chat transcripts in git; vendor object-cloud as the v1 store; make the phone the media authority; replace RFC-0020 retrieval; invent LE/Red/Purple gates; rewrite RFC-0108.

## Acceptance criteria

- [ ] Specs-only in this PR
- [ ] Project records and chat membership persist in the internal DB; `localStorage` is not the source of truth
- [ ] Documented `projects/<id>/media/` layout on the file-owning node
- [ ] Same-PC DB-host stores media on that disk; otherwise Storage Node, with DB metadata pointing at node+path
- [ ] RFC-0109 uploads use this placement; no second blob store; no media-in-SQLite as the file body
- [ ] Phone uploads sync to Leader placement; phone cache is not canonical
- [ ] RFC-0020 workspace sources may attach to the same `project_id`
- [ ] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0121_*.py`); `npm --prefix frontend run build` if portal rail switches to the API. Multi-node storage is swarm/desktop sign-off; single-PC colocation is the required v1 path

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/db/models.py` (project + conversation.project_id); new `backend/app/projects/`; media store used by RFC-0109 implement; companion sync |
| Frontend | `frontend/src/projects.ts` + `App.tsx` rail → Leader API |
| Tests | `tests/test_rfc0121_*.py` — DB membership, colocation path, storage-node pointer, no bytes-in-DB |
| Docs | this RFC; RFC-0118; Architect later: `PORTAL_UX.md` storage sentence |

## Out of scope

Product implementation in this PR. RFC-0020 indexer internals. RFC-0109 analyze/OCR engines (placement only). Full swarm scheduler. S3/minio as required v1. HexStrike. Draft #282.

## Notes

- Implement after RFC-0109 for media paths; chat/folder rows may land in the same named ticket or immediately after.
- `PORTAL_UX.md` “no new public REST resource” is **superseded for projects** by this RFC. Do not edit that Architect file in the implement PR unless CoS names an Architect follow-up.
- Number **0121**. RFC-0119 is reserved (license-package entitlements). RFC-0120 is coding+3D, not this ticket.
