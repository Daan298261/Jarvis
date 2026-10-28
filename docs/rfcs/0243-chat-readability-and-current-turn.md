# RFC-0243: Readable HUD chat and reliable follow-up turns

**Status:** accepted
**Author:** Codex, requested by Daan
**Date:** 2026-10-28

## Problem

The humanoid stage stretches chat across the viewport, leaving opposite-side bubbles far apart and text over a busy canvas. Follow-ups can overlap their previous runner, and the live event stream replays old replies as if they belong to the new question.

## Decision

Keep the existing humanoid and center chat in a bounded column with tighter message spacing. Add a persistent Chat background toggle for a translucent dark reading panel, without canvas backdrop filtering. Drain the prior task runner and its turn-owned background jobs before accepting a follow-up, preserve its committed history, and reset current-turn result/error state. Persist an owner-turn boundary atomically with the follow-up and scope live preview replay to that boundary. Keep the newest user message authoritative while retaining earlier context.

The supplied failure log also exposes ordinary worker continuations restarting durable model keys, a non-streaming deadline that omits output generation, and a server context limit differing from the local estimate. Continue model numbering for every worker continuation, fingerprint actual model inputs and reject mismatched cached model steps. Budget non-streaming calls for generation as well as prompt processing, with a bounded ceiling. Adopt explicit context limits from server overflow errors before retrying and retain the server diagnostic when recovery fails.

## Acceptance criteria

- [ ] HUD chat stays together on wide, desktop and narrow screens; the humanoid stays intact.
- [ ] Chat background can be toggled and survives reload; translucent mode improves contrast without blur/compositor effects.
- [ ] A new prompt cannot run concurrently with or be overwritten by the old runner, and old completion callbacks cannot stop a newer heartbeat.
- [ ] Reconnecting during a follow-up cannot replay previous-turn replies as current output; completed history remains visible.
- [ ] Two distinct prompts reach inference in order, with the second answered as the current request.
- [ ] Ordinary worker follow-ups cannot reuse a previous question's durable model result; identical-input durable replay remains available.
- [ ] Non-streaming deadlines include the requested output budget, and overflow recovery respects a smaller explicitly reported server context.
- [ ] Targeted regressions, full backend CI, frontend build/lint and browser layout/interaction checks run. Installed-app verification is reported separately.

## Scope

`frontend/src/hud/HudChat.tsx`, HUD chat CSS, chat appearance preference, `OwnerChatTranscript`, live preview, task continuation, event streaming, and focused regressions. No architect specifications, model-stack changes, security-gate changes, installer replacement or changes to the existing humanoid.

Failure-log follow-up scope: durable model runner, inference manager, context budgeting and call deadlines, the corresponding inference settings and regression tests. No model selection or security policy changes.
