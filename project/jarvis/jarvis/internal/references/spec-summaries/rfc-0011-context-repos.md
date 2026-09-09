# RFC-0011 — Memory context repositories (digest)

**Full spec:** `docs/rfcs/0011-memory-context-repositories-consolidation.md`

Per-agent **context repos** store durable facts, decisions, and consolidated trajectory lessons with versioning, diff, and revert. API: `/api/context-repo/{agent_id}`. This is **user/project memory**, not the RFC-0060 product-self reference pack. Consolidation can run on swarm nodes with schedule preferences.
