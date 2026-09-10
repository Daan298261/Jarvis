# RFC-0055: Social commentary, interruption policy and butler persona

**Status:** accepted  
**Queue item:** P1 — Context-aware social commentary  
**Author:** ChatGPT design session  
**Date:** 2026-09-08

## Problem

A perception system that notices everything and comments on everything will become irritating almost immediately. Jarvis needs a deliberate policy for deciding *whether* an observation deserves speech, *when* it may interrupt, *how often* similar comments are allowed, and *what tone* to use. This policy must sit between perception and dialogue so the vision model cannot directly generate jokes or intrusive personal remarks.

## Decision

Add a deterministic **Social Commentary Policy** that consumes safe candidate events from RFC-0053 and, optionally, confirmed identity context from RFC-0054. It produces either `suppress` or a bounded `CommentIntent` that a normal dialogue model can phrase using the configured persona.

### Separation of responsibilities

```text
RFC-0053 perception
   -> fact/candidate only
RFC-0055 policy
   -> should comment? category + tone + constraints
normal dialogue model
   -> final wording
RFC-0056 TTS
   -> delivery
```

The vision model never writes the final line.

### User controls

```text
comment_frequency:
  silent
  restrained
  normal
  talkative
  butler

sarcasm:
  off
  light
  dry
  sharp

personal_observations:
  disabled
  practical_only
  casual
  broad

address_style:
  neutral
  sir_maam
  first_name
  configured
```

Recommended defaults:

```text
frequency = restrained
sarcasm = light
personal_observations = practical_only
address_style = neutral
```

The more theatrical `butler + dry/sharp + casual/broad` combination is explicit opt-in.

### Original butler persona

The desired feel is a competent, loyal, mildly judgemental British household AI with dry understatement, but it must be an original Jarvis voice/persona rather than an imitation of Codsworth, Mr. Handy, Stephen Russell, or Fallout dialogue.

Persona traits:

- educated British English register;
- precise, calm, understated delivery;
- dry humour rather than constant punchlines;
- competent and service-oriented first;
- mildly judgemental only when invited by settings;
- `sir`/`ma'am` only when configured and natural;
- no copied catchphrases or character-specific lines;
- never claim to literally be Codsworth or another copyrighted character.

### CommentIntent contract

```json
{
  "kind": "social_comment",
  "topic": "appearance.hair_state",
  "value": "dishevelled",
  "importance": "casual",
  "tone": "dry",
  "address_style": "sir_maam",
  "max_words": 18,
  "must_not_repeat_fact_verbatim": false,
  "context": {
    "novelty": 0.71,
    "confidence": 0.86
  }
}
```

The dialogue prompt receives only the bounded observation necessary for the line, not an image.

### Suppression gates

A comment is eligible only when all relevant gates pass:

1. perception candidate says `safe_to_comment=true`;
2. confidence/novelty thresholds pass;
3. social comments are enabled;
4. category is permitted by `personal_observations`;
5. global cooldown has elapsed;
6. topic-specific cooldown has elapsed;
7. the same fact/semantic line has not recently been said;
8. Jarvis is not listening to the user;
9. the user is not currently speaking;
10. Jarvis is not delivering another response;
11. no urgent alert/decision is active;
12. no high-priority tool operation should be interrupted;
13. quiet hours / focus mode / do-not-disturb allow it;
14. household/guest privacy policy permits it.

### Interruption classes

- `urgent`: safety/system issue; may interrupt ordinary work.
- `practical`: useful environmental observation; wait for a conversational gap.
- `social`: person arrival/return; wait for gap.
- `casual`: appearance/humour; only when idle and cooldown permits.

Appearance jokes can never be `urgent` or `practical` merely because the model assigns high confidence.

### Cooldowns

Suggested starting defaults:

| Frequency | Global spontaneous-comment cooldown | Same-topic cooldown |
| --- | ---: | ---: |
| silent | infinite | infinite |
| restrained | 30 min | 4 h |
| normal | 15 min | 2 h |
| talkative | 7 min | 60 min |
| butler | 4 min | 30 min |

The system also tracks semantic hashes of recently generated comments so paraphrasing does not defeat repetition control.

### Examples

Input candidate:

```text
appearance.hair_state changed tidy -> dishevelled
confidence .86
novelty .71
```

Possible `dry` wording:

> Your hair appears to have adopted a rather independent strategy this morning, sir.

Input candidate:

```text
object=mug transitioned absent -> present repeatedly today
```

Possible line only if the count is actually known from structured observation history:

> Another coffee, sir. I shall refrain from keeping score. For now.

Do not fabricate `third cup`, elapsed hours, clothing changes, or other history unless the state store actually supports the claim.

### Personal-observation boundaries

Even with `broad`, do not generate appearance-based statements about:

- weight/body size;
- attractiveness/ugliness;
- race/ethnicity;
- disability/medical state;
- pregnancy;
- intoxication/drug use;
- mental-health diagnosis;
- religion/political identity;
- sexuality;
- precise age.

`broad` expands harmless style/habit commentary, not sensitive inference.

### Guest / multi-person behavior

When an unknown or non-owner person is present:

- default to practical comments only;
- suppress personal appearance jokes;
- do not announce stored facts about the owner;
- do not reveal another person's enrollment label unless configured;
- allow owner to configure household-specific profiles later.

### Dialogue generation

Use a small prompt/template around the existing dialogue model rather than a dedicated large model.

System constraint example:

```text
Generate one short household-assistant remark from CommentIntent.
Do not add facts.
Do not mention confidence, camera, vision model, or internal policy.
Do not diagnose or infer sensitive traits.
Match the requested tone.
Return one sentence unless the intent explicitly permits two.
```

For very low-resource operation, deterministic templates may cover common events and bypass LLM generation entirely.

### Feedback / learning

Provide lightweight feedback actions:

- `More like this`
- `Less like this`
- `Don't comment on this topic`
- `Too sarcastic`

Feedback updates explicit preference/cooldown/topic suppression state. It does not silently retrain the vision model.

### API/event integration

Policy should expose internal methods first; optional owner diagnostics:

- `GET /api/perception/commentary/status`
- `GET /api/perception/commentary/recent` — intents/reasons, not raw frames;
- `POST /api/perception/commentary/feedback`

Normal dialogue receives comment intents through the local event/task bus rather than polling camera state.

## Acceptance criteria

- [ ] Candidate facts cannot directly speak without passing commentary policy.
- [ ] Frequency/sarcasm/personal-observation settings are validated and persisted.
- [ ] Same fact cannot generate repeated comments inside topic cooldown.
- [ ] Casual comments are suppressed while user/Jarvis is speaking or urgent work is active.
- [ ] Appearance humour is limited to harmless allowlisted categories.
- [ ] Unknown/guest presence suppresses personal owner commentary by default.
- [ ] Generated wording is constrained to supplied facts; tests catch invented counts/history.
- [ ] User feedback can suppress a topic without disabling all perception.
- [ ] Persona is original and does not depend on copyrighted Fallout assets/dialogue.
- [ ] Unit tests cover frequency profiles, interruption gates, category boundaries, guest behavior and repetition.
- [ ] `python3 -m pytest` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Policy | `backend/app/perception/commentary.py` |
| Persona | `backend/app/persona/social.py` or existing persona layer |
| Config | `backend/app/config.py`, `backend/app/api/settings.py` |
| Event integration | existing local BUS / dialogue path |
| Tests | `tests/test_social_commentary.py` |

## Out of scope

- Camera/VLM observation — RFC-0053.
- Biometric identity matching — RFC-0054.
- TTS engine/voice design — RFC-0056.
- General long-term psychological profiling.
