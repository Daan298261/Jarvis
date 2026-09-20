# RFC-0132: Supermemory semantic recall sidecar

**Status:** accepted
**Owner:** Jarvis Core
**Created:** 2026-09-20
**Upstream:** `supermemoryai/supermemory` (`server-v0.0.8`, Windows x64 SHA-256 pinned by bootstrap)

## Problem

Jarvis has authoritative, versioned structured memory and an owner-editable Obsidian vault, but ContextRepo recall is lexical. Paraphrases and long-horizon associations can be missed, while putting more history into the live prompt worsens context pressure.

## Decision

Add the self-hosted Supermemory server as an optional loopback-only semantic recall sidecar.

- Jarvis ContextRepo remains the authoritative fact, provenance, mutation, conflict, and rollback store.
- Accepted ContextRepo mutations are mirrored to Supermemory with stable custom IDs when mirroring is enabled.
- Per-turn memory retrieval uses bounded Supermemory hybrid search when configured and healthy.
- Any missing configuration, timeout, HTTP/schema failure, or empty result falls back to the existing native ContextRepo lookup without blocking the turn.
- Supermemory credentials are stored in the existing credential store and are never returned by status/settings APIs.
- The sidecar is installed on demand from a pinned, checksum-verified GitHub release; no binary or upstream source tree is committed to Jarvis.
- Jarvis preserves the upstream self-hosted Lite license and its 10,000-document limit.
- Remote endpoints are rejected by default. An owner must explicitly enable remote access before private memory may leave loopback.

## Obsidian boundary

Obsidian remains the human-readable, owner-editable linked knowledge brain: notes, project material, wiki-links, graph navigation, and durable source documents. Supermemory adds semantic retrieval and extracted memory associations. It does not replace the vault UI or become the source of truth. Vault retrieval and Supermemory recall are independently optional and both contribute only bounded excerpts to a turn.

## Acceptance criteria

- [x] A pinned Windows bootstrap downloads from the official GitHub release and verifies SHA-256 before activation.
- [x] Status, credential binding, configuration, probe, search, and ContextRepo sync APIs expose no secret values.
- [x] Working-set composition injects at most a small bounded set of semantic memories with provenance.
- [x] Supermemory timeout, unavailability, malformed response, disabled state, and empty results use native ContextRepo fallback.
- [x] ContextRepo writes remain successful if the sidecar is unavailable.
- [x] Tests cover search parsing, loopback policy, prompt bounds, mutation mirroring, and native fallback.
- [x] Existing RFC-0011 ContextRepo and RFC-0107 Obsidian behavior remains intact.

## Likely files

- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/api/supermemory.py`
- `backend/app/memory/supermemory.py`
- `backend/app/memory/repository.py`
- `backend/app/agent/turn_working_set.py`
- `scripts/bootstrap-supermemory.ps1`
- `tests/test_rfc0132_supermemory.py`

## Sign-off boundary

Unit tests and mocked REST tests can run in CI. Downloading the ~278 MiB Windows sidecar, first-boot extraction against a live local LLM, semantic quality, upgrade/backup recovery, and latency under the owner workload require Windows desktop sign-off.

## Implementation evidence

Windows desktop smoke on 2026-09-20 verified the pinned SHA-256, a 899 ms loopback boot, local `bge-base-en-v1.5` embeddings, queued ContextRepo ingestion, and semantic retrieval of the ingested canary. Upgrade/backup recovery and sustained owner-workload latency remain release sign-off, not unit-test claims.
