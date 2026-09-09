# Jarvis internal reference pack

This directory is the **primary** corpus for RFC-0060 docs-first grounding. When a user asks about Jarvis itself, reports an on-screen error, or is within the post-install / version-bump budget window, the agent retrieves from here **before** guessing from general knowledge.

## How grounding uses this pack

1. **Trigger** — system-about questions, pasted Jarvis errors, or the new-install budget (~100 chat turns after a version bump).
2. **Search** — local keyword retrieval across this pack, then allowlisted in-repo docs (`docs/`, `README.md`, `TROUBLESHOOTING.md`, etc.). Paths cannot escape those roots.
3. **Prompt** — ranked snippets are injected with citation ids. The model must prefer these citations and admit gaps instead of inventing product behavior.
4. **Privacy** — no external web fetch for self-about queries; secrets in snippets are redacted.

## Index

| File | Topic |
| --- | --- |
| [capability-overview.md](capability-overview.md) | What Jarvis can and cannot do |
| [setup-pitfalls.md](setup-pitfalls.md) | Install, LAN, models, GPU, lifecycle, secrets |
| [spec-summaries/](spec-summaries/) | Short digests of key RFCs and root specs |

Full RFCs and architect specs remain in `docs/rfcs/` and repo root `*.md` files; this pack holds **concise** product-facing summaries only.
