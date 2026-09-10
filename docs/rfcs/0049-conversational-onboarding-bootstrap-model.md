# RFC-0049 — Conversational onboarding, self-configuration, and bootstrap model

Status: Implemented

## Problem

Jarvis exposes extensive configuration, but first-run setup currently asks the owner to understand node roles, resource budgets, inference profiles, runtimes, and model selection before the system becomes useful. Model cards also expose provisional numeric scores without enough plain-language context, and a normal Windows installer excludes model weights and downloads them during bootstrap.

The desired product behavior is closer to an appliance: install Jarvis, talk or type briefly, let Jarvis configure itself, and remain minimally useful even before optional model downloads complete.

## Goals

1. Make first-run setup a short conversational interview rather than a technical wizard.
2. Accept typed answers and, when browser/desktop speech recognition is available, spoken answers.
3. Ask only high-value questions and infer the rest from hardware.
4. Persist the answers and the resulting configuration.
5. Produce an explicit setup plan showing what Jarvis will configure and which models it recommends.
6. Generate an idempotent PowerShell download script for the selected optional models.
7. Clearly expose every currently loaded model/runtime and its role.
8. Replace opaque model-card scoring with plain-language performance tiers, workload fit, strengths, limitations, memory footprint, and evidence status.
9. Ship a usable local bootstrap model in Windows release distributions.
10. Keep the existing detailed setup controls available as an Advanced path.

## Non-goals

- Removing manual model/runtime configuration.
- Forcing every specialist model to be resident simultaneously.
- Hiding security-role authorization behind onboarding.
- Shipping remote/API credentials in the installer.
- Treating estimated benchmark scores as measured local performance.

## Bootstrap model

The smallest official Ornith 1.5 release is Ornith-1.5-9B. Jarvis therefore uses a quantized `ornith-ai/Ornith-1.5-9B-GGUF` Q4_K_M build as the bootstrap model.

Release builds stage the GGUF into `installer/windows/payload/models/bootstrap/` before Inno Setup compilation. `Jarvis.iss` copies that payload to `{app}/models/bootstrap/`. The repository does not commit multi-gigabyte weights.

Development/source installs retain an idempotent download fallback if the bundled file is absent.

The bootstrap model is deliberately classified as `bootstrap/orchestrator`: sufficient for setup conversation, basic chat, routing, simple tool selection and recovery. It is not presented as the best model for hard coding, deep reasoning, vision, or specialist security work.

## Interview

The default interview is intentionally short. Hardware detection happens automatically and is not a question.

### Q1 — Primary use

`What do you mainly want Jarvis to do?`

Choices/tolerant natural-language mapping:
- Everyday assistant / automation
- Coding / development
- Research / writing
- Security / monitoring
- A bit of everything

Multiple intents may be selected from free text.

### Q2 — Locality / cost preference

`How should I balance local privacy, speed and cloud quality?`

- Local first (default)
- Best result, cloud escalation allowed
- Cheapest practical
- Local only

### Q3 — Resource aggressiveness

`How much of this computer may Jarvis use while you are using it?`

- Light (~25%)
- Balanced (~50%, default)
- Aggressive (~80%)
- Maximum when needed

Jarvis still applies detected hardware constraints.

### Q4 — Voice

`Do you want to use voice with Jarvis?`

- Yes
- No

When yes, Jarvis enables the voice components already supported by the installation. Speech input for the interview itself is opportunistic and does not require this answer.

### Optional security follow-up

Only when security is selected:

`Do you want defensive monitoring tools prepared?`

This may recommend/configure Blue/DFIR components, but it MUST NOT silently unlock Red or Blue security model gates. Existing password and Red authorization controls remain authoritative.

## Deterministic planner

The interview is conversational in presentation, but configuration output MUST be deterministic and inspectable. The planner combines:

- detected CPU/RAM/GPU/VRAM/disk;
- primary-use intents;
- locality/cost policy;
- resource preference;
- voice preference;
- existing installed-model inventory.

It emits:

```json
{
  "settings_patch": {},
  "setup_state_patch": {},
  "recommended_models": [],
  "download_models": [],
  "keep_loaded": [],
  "reasoning": []
}
```

The owner sees this summary before Apply. Applying writes existing Jarvis settings/setup state and never bypasses security gates.

## Model recommendation policy

Baseline:
- `Ornith-1.5-9B Q4_K_M`: bundled bootstrap, always available, default orchestrator/fallback.

Hardware permitting:
- general/leader: Qwen3.8-27B quantized, on demand;
- blue/SOC: RedSage 8B, optional and gate-controlled;
- DFIR: Imperum 35B-A3B, optional/on demand;
- red: DeepHat 7B may be recommended but remains gate/authorization controlled;
- voice components are selected separately.

The planner MUST label whether a model is `bundled`, `installed`, `recommended download`, `remote`, or `unavailable`.

## Download-plan script

`POST /api/setup/interview/plan` returns the model plan. `POST /api/setup/interview/download-script` materializes `data/setup/download-models.ps1` from that plan and also returns the script text.

Requirements:
- PowerShell 5.1 compatible;
- idempotent;
- creates model directories;
- installs/uses `huggingface_hub` via Jarvis venv where needed;
- uses exact repository IDs and quantization include patterns;
- skips already-present GGUF files;
- bootstrap model is omitted from optional downloads when already bundled/present;
- no API tokens embedded in generated output;
- non-zero exit on failed required downloads.

## Loaded model visibility

The Model page gets a prominent `Loaded now` section. It distinguishes:

- primary managed inference model;
- externally served/advertised model(s);
- enabled specialist runtime profiles;
- loaded versus configured versus merely installed.

A model name must never be inferred solely from the configured profile when the runtime reports an advertised model ID.

## Model performance cards

Cards should answer in seconds:

- What is this model good at?
- What is it bad at?
- Is it fast on this PC?
- Does it fit in VRAM?
- What role should Jarvis give it?
- Is the score measured locally or estimated?

Replace bare `Overall 8.4` emphasis with:

- capability tier: `Excellent / Strong / Good / Basic / Limited`;
- recommended roles;
- three strongest workload axes;
- two weakest workload axes;
- plain-language strengths and limitations;
- estimated footprint and fit label;
- evidence badge: `Jarvis measured`, `published/estimated`, or `unknown`.

Numeric axis bars remain available as secondary detail.

## UX

First run opens the neural HUD with an onboarding panel integrated around the orb. The question is read aloud when speech output is available and the owner may type or use speech recognition. Answers should be short. A `Use recommended defaults` action can complete setup immediately from detected hardware.

`Advanced setup` links to the existing detailed wizard rather than deleting it.

## Persistence

Store interview answers and generated plan in `data/setup_state.json` under versioned fields:

- `onboarding_version`
- `interview_answers`
- `interview_plan`
- `selected_models`
- `download_script_path`

Re-running onboarding updates these fields without erasing unrelated setup/security state.

## Security

- Onboarding never stores spoken audio unless existing explicit voice-recording settings say otherwise.
- Free-text answers are local setup data.
- Generated scripts never contain authentication secrets.
- Security model gates remain independent and authoritative.
- Red Team cannot be enabled merely by answering onboarding questions.

## Acceptance criteria

- Fresh setup can be completed with four core answers plus one optional security follow-up.
- Typed onboarding works with no microphone.
- Speech input is optional and degrades to typing without blocking setup.
- Applying a plan changes existing settings/budget/role policy rather than maintaining a second configuration system.
- `download-models.ps1` is generated from the selected model plan and is safe to rerun.
- Model page visibly identifies loaded model(s).
- Installed model cards show understandable strengths, weaknesses, workload fit and evidence status.
- Windows release build stages and packages Ornith-1.5-9B Q4_K_M as bootstrap weights.
- Installer can finish offline with respect to model weights when built with the bootstrap payload.
- Existing security gates cannot be bypassed.
- Frontend build and setup/model tests pass.
