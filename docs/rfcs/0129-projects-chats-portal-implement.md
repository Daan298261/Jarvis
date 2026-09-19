# RFC-0129: Projects, chats in DB, portal rail (implement)

**Status:** accepted  
**Parent spec:** [RFC-0121](0121-projects-folder-chats-db-media-placement.md)  
**Author:** Cursor cloud worker  
**Date:** 2026-09-19

## Problem

Portal project grouping lived in `localStorage` while chats and tasks needed Leader DB persistence and agent tooling per RFC-0121.

## Decision

Use `PortalProject` / `PortalProjectLink`, `/api/projects`, owner-chat persistence via `portal_store`, portal rail API fetch + `import-local` migration, `chat_projects` tool, and `data/projects/<id>/media` on project create.

## Out of scope

Storage-node placement, RFC-0109 ingest, `PORTAL_UX.md` edits.
