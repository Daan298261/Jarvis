# RFC-0117: Tiny front-chat responder

**Status:** accepted  
**Queue item:** Universal low-latency reply while larger model/tool work continues  
**Author:** Taco request via Codex  
**Date:** 2026-09-18

**Related:** [RFC-0085](0085-universal-task-fastpath.md) response-first routing, [RFC-0075](0075-natural-speak-path-and-reply-latency.md) natural speak path, [RFC-0083](0083-conversation-followup-no-reasoning-leak.md) no reasoning leak, [RFC-0115](0115-ornith-orchestrator-router-complexity.md) model tiers and visible handoff, [RFC-0116](0116-typesafe-jev-optional-decision-tier.md) optional decision tier.

## Problem

Jarvis still feels slow even when the loaded model is not the 27B model. The delay is systemic: routing, prompt prefill, hidden thinking, tool setup, long context, and TTS can all block the first useful response. The owner experience should not depend on whichever large model is currently processing. Jarvis needs a tiny always-warm front-chat model that can answer or acknowledge immediately, while a larger model continues deeper reasoning, tool work, or verification in the background.

## Decision

Add a dedicated **front responder** lane. It is a tiny local chat model, always warm when possible, with a strict job: produce a fast first response for the owner. It may answer trivial/basic turns directly, provide a concise acknowledgement for deeper work, ask a short clarification when required, or say that a stronger model is taking over. It must not perform deep reasoning, long-context synthesis, tool execution, coding changes, security analysis, or final claims that need verification.

The front responder runs before, or in parallel with, the normal router/agent path. The larger model remains responsible for the final answer whenever the request exceeds the front responder's tier. The UI and voice path should make this feel like one Jarvis turn, not two assistants arguing.

### 1. Front responder role

Add a runtime role:

```text
front_responder
```

Recommended default profile:

```text
runtime_role = front_responder
answer_tier = 1
max_output_tokens = 96-160
temperature = low
thinking = false
tools = disabled
context_budget = small envelope only
```

Candidate models may be any small local instruct/chat model that reliably starts quickly on the reference desktop. The implementation should not hard-code one vendor/model name. The owner may configure the exact model in settings later, but this RFC requires the architecture to support the lane.

### 2. Two-lane turn flow

Every owner chat turn enters two lanes:

```text
owner message
  -> tiny front responder: fast first reply / ack / clarification
  -> normal router + larger model/tool path: final answer or action result
```

For trivial turns, the front responder may complete the whole turn:

```json
{
  "front_action": "final_basic",
  "text": "Hi, sir."
}
```

For non-trivial turns, it emits a fast first response while the deeper path continues:

```json
{
  "front_action": "ack_continue",
  "text": "On it. I'll give you the quick answer first and check the deeper details in parallel."
}
```

Allowed front actions:

```text
final_basic
ack_continue
ask_clarification
handoff_notice
silent_skip
```

`silent_skip` is only allowed when a first response would be harmful or noisy, for example when the next event is already streaming within the configured budget.

### 3. Budgets

Reference desktop targets:

```text
first visible text: <= 700 ms target, <= 1500 ms acceptable
first audible speech: <= 1200 ms target, <= 2500 ms acceptable
front responder total output: <= 3 seconds
```

These are owner-experience budgets, not tok/s benchmarks. Measurements must include queue time and TTS start time where applicable.

### 4. Safety and truthfulness

The front responder must not:

- claim an action succeeded before the worker verifies it;
- invent live facts;
- summarize repository/runtime state without evidence;
- expose hidden reasoning;
- mention internal routing score dumps;
- use tools;
- answer tier-2+ requests as if it were the final authority.

For deeper requests it should use grounded transitional language:

```text
I can start with the short version while I check the details.
```

Bad:

```text
Done, I fixed it.
```

before verification.

### 5. One transcript, not duplicate answers

The transcript should treat the front response as the start of the same Jarvis turn. When the larger model finishes, it should either:

- replace/complete the initial answer;
- append a clearly labeled deeper result;
- or stay silent if the front responder already fully answered and no deeper path ran.

The owner should not see repeated "Jarvis:" blocks for the same thought. Work/progress events stay behind the existing collapsed work panel unless they are user-facing handoff messages.

### 6. Voice behavior

If speech is enabled, the front response is eligible for immediate TTS after the existing speak filter. The deeper answer may interrupt, continue, or be skipped according to existing barge-in/speech rules, but TTS must not wait for the larger model before speaking a safe acknowledgement.

### 7. Interaction with RFC-0115

RFC-0115 owns model tiering and automatic escalation. This RFC adds a lower-latency front lane before the tiered responder finishes. The front responder is not the same as the orchestrator unless the selected tiny model can satisfy both roles within budget. If one model does both, keep the contracts separate in code:

```text
front_responder = first user-facing response
orchestrator = routing/model selection
worker = final answer/action
```

### 8. Observability

Record per-turn timing:

```json
{
  "front_model": "configured-small-model",
  "front_action": "ack_continue",
  "front_first_text_ms": 640,
  "front_first_audio_ms": 1180,
  "router_ms": 320,
  "worker_first_text_ms": 5600,
  "worker_complete_ms": 12400,
  "tts_first_audio_ms": 1180
}
```

Events:

```text
front_response_started
front_response_completed
front_response_skipped
worker_response_started
worker_response_completed
```

Expose concise timing in diagnostics so the owner can see whether slowness is front responder, router, model load, tool work, TTS, or audio output.

## Acceptance criteria

- [ ] A configured tiny front responder lane exists with tools disabled, thinking disabled, and a small token cap.
- [ ] Owner chat starts the front responder before or in parallel with the normal router/worker path.
- [ ] Trivial greetings and basic chat can complete through `final_basic` without invoking a larger worker.
- [ ] Non-trivial requests emit a safe `ack_continue` or `handoff_notice` quickly while the larger model/tool path continues.
- [ ] The front responder cannot make unverified success claims, perform tools, expose hidden reasoning, or answer tier-2+ requests as final.
- [ ] Transcript rendering treats the front and worker output as one Jarvis turn, without duplicate reply cards.
- [ ] Speech can begin from a safe front response without waiting for the larger model.
- [ ] Diagnostics record queue, front first text, front first audio, router, worker first text, worker completion, and TTS/audio timings.
- [ ] Unit tests cover `final_basic`, `ack_continue`, `ask_clarification`, safety rejection, no-tools/no-thinking config, and transcript merge behavior.
- [ ] `python -m pytest` passes for focused tests; `npm --prefix frontend run build` passes if transcript UI changes.
- [ ] Windows desktop sign-off measures first visible and first audible response across at least two larger backend models, proving the fix is not 27B-specific.

## Still missing to actually fix speed

- [ ] Implement the tiny front responder lane.
- [ ] Start it before or in parallel with normal routing.
- [ ] Merge tiny reply + larger reply into one Jarvis turn.
- [ ] Let safe acknowledgements speak immediately.
- [ ] Add timing diagnostics for queue, front text/audio, router, worker text/complete, and TTS/audio.
- [ ] Desktop-test first visible and first audible response across at least two larger models.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/loop.py`, `backend/app/agent/planning.py`, `backend/app/persona/owner_chat.py`, `backend/app/inference/runtime_profiles.py`, `backend/app/inference/manager.py`, new `backend/app/agent/front_responder.py` |
| Voice | `backend/app/persona/chat_delivery.py`, `backend/app/tts/*` timing hooks |
| Frontend | `frontend/src/chat/ownerChatView.ts`, `frontend/src/chat/OwnerChatTranscript.tsx`, `frontend/src/hud/HudChat.tsx` |
| Tests | `tests/test_front_responder.py`, `tests/test_owner_chat_greeting.py`, transcript/voice timing tests |
| Docs | this RFC only; Architect may later add a queue line |

## Out of scope

Choosing a permanent bundled small model, downloading model weights, changing Kokoro/Chatterbox voice quality, replacing RFC-0115 model routing, implementing full swarm parallelism, or modifying Architect-owned master/spec documents.

## Notes

The owner explicitly reported that the delay occurs across models, not only with the 27B model. The implementation must measure perceived response latency and must not treat model tok/s alone as proof. A tiny model that answers quickly while a bigger model thinks is the desired owner experience.
