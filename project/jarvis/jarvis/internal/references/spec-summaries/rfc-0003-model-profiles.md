# RFC-0003 — Runtime model profiles & routing (digest)

**Full spec:** `docs/rfcs/0003-runtime-model-profiles-routing.md`

Jarvis names inference **RuntimeProfiles** (Fast / Balanced / Quality / Expert) with quant, context size, thinking mode, and backend binding. The portal model picker and `POST /api/model/load` select a profile; agent **execution modes** (fast/balanced/reliable) are separate from GGUF choice. `AUTO` routing may pick profiles from hardware signals (RFC-0018) without replacing explicit user pins.
