# RFCs (design → implementation handoff)

ChatGPT/Codex and human design work lands here as **short RFCs** — one concern per file. RFCs are the ticket Cursor cloud workers implement.

## Rules

1. **One concern per RFC.** Split large designs into multiple numbered files (`0001-…`, `0002-…`).
2. **Do not rewrite `JARVIS_MASTER_PLAN.md`.** The master plan stays architecture + Current State + Development Queue. Update it only **after** an RFC is merged (matching queue lines and state bullets).
3. **Keep RFCs small:** problem, decision, acceptance criteria, likely files. Target &lt; 2 pages.
4. **Product features** (Browser Use, swarm, P4/P5, model-stack migrations) get their own RFC; they do not belong in a process or hygiene RFC.

## Workflow

```
ChatGPT/Codex  →  docs/rfcs/NNNN-title.md  →  queue line in master plan (optional)
                                                      ↓
Cursor worker  →  branch from cursor/local-qwen-desktop-agent  →  PR  →  merge
                                                      ↓
                                            update §57–58 + decision log only
```

## Template

Copy [`TEMPLATE.md`](TEMPLATE.md) to `docs/rfcs/NNNN-short-slug.md` and fill it in.

## Naming

- `NNNN` — four-digit sequence (`0001`, `0002`, …).
- `short-slug` — kebab-case summary (`playwright-retry`, `auth-header-fix`).

## Status values

| Status | Meaning |
| --- | --- |
| `draft` | Design in progress; do not implement yet |
| `accepted` | Ready for a Cursor worker (named in the launch prompt) |
| `implemented` | Merged; master-plan queue/state updated |
| `superseded` | Replaced by another RFC; link the successor |
