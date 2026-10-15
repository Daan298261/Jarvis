# RFC-0222: Persistent mobile memory and quick answers

**Status:** accepted
**Author:** Codex, requested by Daan
**Date:** 2026-10-15

## Problem
Recent chat buffers do not provide durable cross-chat recall. Phone context and RAM are limited; normal Q&A should prefer fast installed models.

## Decision
Add an encrypted SQLite archive with chats, messages (chat ID, sender, project, timestamp), extractive summaries, project notes and owner-authored instructions. Migrate the existing recent-history file idempotently without modifying it; SQLite becomes authoritative, with bounded/paged UI reads and transactional row writes. Index keyed hashes of words rather than plaintext content. Recall only relevant messages from the global/current project scope, retain provenance, distinguish historical text from owner instructions, and budget the complete final prompt with the real tokenizer. Provide inspect/delete/disable controls. Archive content is local; do not silently upload memory to desktop/cloud.

Offer Quick/Detailed answers; Quick prefers the smallest installed pinned minimal-refusal model and shorter output. No automatic weight downloads. Optional short-lived warm model residency releases on background/memory pressure. Jev and Laya are typed decision engines, not chat generators: optional paired-desktop routing uses real adapters, explicit Jev cloud consent plus existing owner entitlement/privacy gates, deadlines, and honest fallback labels. Offline uses local routing and text generation only.

User follow-up: fix Pocket TTS IR 13 incompatibility by upgrading the hash-pinned native ONNX Runtime to 1.31.0, with version/hash-specific extraction to prevent stale headers/libraries. Validate all pinned Pocket graphs against the same runtime. Keep detailed exceptions in diagnostics and show concise recovery notifications.

## Acceptance
- Full archive survives restarts, beyond the recent UI buffer; summaries and indices update transactionally; replay is idempotent.
- Migration preserves legacy files; deleting chat/project memory removes summaries/index entries and stops recall.
- No plaintext conversation/notes/instructions or search tokens in database/WAL; no embeddings model or full-history scan per prompt.
- Project/global instructions and notes have an editable UI; different projects cannot leak recall into each other.
- Final prompt including memory fits the token budget, preserves newest request, and avoids duplicate latest turns.
- Quick mode respects installed weights, owner selection in Detailed, Offgrid minimal-refusal restriction, model availability and pressure gates.
- Decision routing never bypasses permissions or presents rules as Jev/Laya; no offline/cloud calls without required consent.
- Android regression tests/build/lint/runtime checks and focused backend/CI pass; physical phone RAM/speed acceptance stays separate.

## Scope
Android memory/context/model choice/UI; authenticated companion decision-routing endpoint and tests. No Architect-owned spec edits.

## Research
- https://www.sqlite.org/fts3.html : plaintext FTS would expose decrypted content; use keyed token lookup with encrypted payload rows instead.
- https://github.com/NandhaKishorM/laya : typed choices/scores/noul, no general text generation; ONNX exports exist but no integrated Android tokenizer/checkpoint/runtime contract here. Reuse the installed desktop adapter, do not advertise a phone-native Laya engine.
- https://typesafe.ai/ : reuse owner-configured TypeSafe adapter and privacy/entitlement checks; do not put API keys on phone.
- Use bounded summaries + lexical retrieval + recent turns; model-sized KV context remains bounded. Warm residency trades RAM for repeat-turn speed and is opt-in/released promptly.
