# RFC-0056: Expressive voice runtime and original British-butler voice

**Status:** accepted  
**Queue item:** P1 — Expressive local Jarvis voice  
**Author:** ChatGPT design session  
**Date:** 2026-09-08

## Problem

Jarvis's visual/social presence will feel incomplete if spontaneous remarks are delivered with a generic system voice. The desired experience is a polished household-assistant voice with the dry, competent, slightly theatrical character associated with classic British robot/butler performances. It must remain low-latency, local-capable, swappable across hardware tiers, and legally/creatively original rather than cloning a recognizable actor or copyrighted character voice.

## Decision

Introduce a provider-neutral **Expressive TTS runtime** with an original Jarvis voice profile. The runtime separates semantic text, delivery instructions and audio synthesis so social commentary, normal chat, alerts and narration can choose different latency/quality paths without changing dialogue logic.

### Voice design target

Original voice specification:

```text
Language: primarily English, multilingual optional
Accent: contemporary educated British English
Age impression: mature adult
Timbre: warm, composed, lightly synthetic; not an impression of a named actor
Cadence: deliberate but conversational
Register: precise, service-oriented, understated
Humour delivery: dry; micro-pause before/after punch line where natural
Emotion: restrained, never cartoonishly exaggerated by default
Address: optional "sir"/"ma'am" according to RFC-0055 settings
```

Explicit non-goals:

- do not clone Stephen Russell or any other identifiable actor without rights/consent;
- do not extract/use Fallout/Codsworth/Mr. Handy voice assets;
- do not market the voice as Codsworth or claim identity with that character;
- do not copy character catchphrases/dialogue.

The goal is the *interaction style*—competent British household AI with dry humour—not voice impersonation.

### Runtime abstraction

```py
class TTSProvider(Protocol):
    async def synthesize(self, request: SpeechRequest) -> SpeechResult: ...
```

Canonical request:

```json
{
  "text": "Your hair appears to have adopted a rather independent strategy this morning, sir.",
  "voice_id": "jarvis_butler_v1",
  "purpose": "social_comment",
  "priority": "interactive",
  "style": {
    "pace": 0.98,
    "warmth": 0.55,
    "dryness": 0.75,
    "energy": 0.35,
    "pause_strength": 0.6
  }
}
```

Provider adapters translate the normalized style into supported engine controls. Unsupported controls are ignored deterministically rather than embedded as text unless the engine explicitly supports instruction tags.

### Candidate engines

Benchmark at least these local-capable classes:

1. **Kokoro 82M** — very small/fast baseline; Apache-licensed weights; useful for low-resource and fast response.
2. **Qwen3-TTS 0.6B / 1.7B** — expressive/streaming models with voice design and instruction control; Apache-2.0 project. Candidate for high-quality voice creation and multilingual use.
3. **Chatterbox / Chatterbox Turbo** — expressive open-source TTS with emotion/paralinguistic capabilities; candidate for richer social delivery where packaging/license/dependency checks pass.
4. **Piper** or existing lightweight fallback — CPU/edge fallback where neural expressive engines are unavailable.

No engine is selected solely from public demos. Jarvis benchmark must measure target-machine latency, VRAM/RAM, first-audio latency, real-time factor, stability, pronunciation and subjective voice fit.

### Routing

TTS routing is independent from LLM routing.

Suggested profiles:

```text
voice.fast
  -> lowest first-audio latency, CPU/low VRAM acceptable

voice.balanced
  -> default conversational quality

voice.expressive
  -> social commentary, narration, premium presence

voice.edge
  -> Pi/low-end node fallback
```

Router inputs:

- purpose (`chat`, `social_comment`, `alert`, `narration`);
- configured voice preference;
- local-only/cloud policy;
- GPU/CPU pressure;
- whether primary inference currently owns VRAM;
- first-audio latency history;
- engine availability;
- language.

Primary reasoning/model inference must not be evicted merely to say a non-urgent ambient joke. The voice router may fall back to a lighter TTS engine under load.

### Streaming / latency

Interactive target:

- begin audio as soon as a coherent initial chunk is ready;
- prefer sentence/phrase streaming where supported;
- cancellation must stop queued and currently playing social speech promptly;
- new urgent system alerts may pre-empt casual speech;
- social remarks may not pre-empt user speech.

Collect local metrics:

- text-to-first-audio ms;
- real-time factor;
- synthesis duration;
- playback queue delay;
- cancellations;
- fallback reason;
- GPU/RAM footprint.

### Voice asset model

Jarvis voice packs are separate from code.

```text
voice_pack:
  id: jarvis_butler_v1
  display_name: Jarvis Butler
  provenance: original / licensed
  supported_engines: [...]
  language_profiles: [...]
  license_manifest: ...
  hashes: ...
```

A pack may include engine-specific speaker embeddings/reference audio only when Jarvis has rights to distribute/use them. Provenance is mandatory for commercial packaging.

### Creating the original voice

Preferred order:

1. use a voice-design model that synthesizes a new voice from textual attributes, where licensing permits;
2. commission/record a consenting voice actor and create a licensed embedding/model;
3. use a permissively licensed stock voice as fallback.

Do not create the production voice by feeding recognizable Codsworth/Stephen Russell samples into a cloning model.

### Delivery planner

Dialogue text should remain clean. A small deterministic delivery planner maps purpose/persona to synthesis controls.

Examples:

```text
alert:
  pace 1.02, energy .55, dryness .10, minimal flourish

normal assistant reply:
  pace 1.00, warmth .55, dryness .25

social dry remark:
  pace .96, warmth .50, dryness .75, mild pause emphasis

long narration:
  pace .94, warmth .62, stable energy
```

### Paralinguistic events

Where the engine supports tags such as laugh/chuckle/sigh, use them sparingly and only through structured delivery directives. The LLM does not get unlimited ability to inject arbitrary engine tags.

Allowlisted events might include:

- soft chuckle;
- brief sigh;
- breath/pause.

Never add involuntary-sounding coughs, distress sounds or loud effects by default.

### Audio output integration

- one local playback queue with priorities;
- route to configured output device;
- support immediate cancel/duck;
- expose speaking state to UI/humanoid presence;
- expose normalized audio amplitude/phoneme timing when available for avatar animation;
- do not store synthesized audio by default;
- optional cache may store deterministic non-personal UI phrases, not spontaneous personal comments unless explicitly enabled.

### Security / privacy

- Local TTS remains local under `LOCAL ONLY`.
- Voice reference audio/embeddings are treated as sensitive assets.
- No automatic upload of a user's voice samples to cloud TTS.
- Cloud voice providers, if supported later, require explicit credentials/provider choice.
- Social-comment text is not retained merely because it was spoken.

### Premium packaging

The provider abstraction and basic voice functionality belong to core Jarvis. A polished high-quality `jarvis_butler_v1` voice pack and expressive/cinematic integration may be a paid Presence entitlement, while a functional local fallback remains available to all users.

Do not make normal accessibility TTS dependent on a premium license.

### Benchmarks / selection gate

Before selecting the production engine/pack, record on target machines:

- first-audio latency for 10, 30 and 100-word utterances;
- RTF;
- peak VRAM/RAM;
- concurrent impact on loaded 9B/27B inference;
- interruption/cancel latency;
- pronunciation of names, technical terms and Dutch/English mixed text;
- subjective MOS-style owner ratings for naturalness, authority, warmth and dry-humour delivery.

### Acceptance criteria

- [ ] TTS is accessed through a provider-neutral request/result API.
- [ ] Fast/balanced/expressive/edge routing does not require dialogue-code changes.
- [ ] Casual speech yields resources to primary reasoning work when necessary.
- [ ] Playback can be cancelled and urgent audio can pre-empt casual audio.
- [ ] Speaking state is available to the visual presence layer.
- [ ] Production voice has documented provenance and distribution rights.
- [ ] No Codsworth/Fallout/actor voice assets are bundled or used for cloning.
- [ ] At least two local TTS candidates are benchmarked before production selection.
- [ ] A non-premium functional local TTS fallback remains available.
- [ ] Unit tests cover routing, fallback, cancellation priority and style mapping.
- [ ] `python3 -m pytest` passes; frontend build passes if UI changes.

## Likely files

| Area | Paths |
| --- | --- |
| Voice runtime | existing `backend/app/api/voice.py`, new provider layer under `backend/app/voice/**` |
| Routing | `backend/app/voice/router.py` |
| Packs | voice pack manifest/inventory under existing pack architecture |
| Config | `backend/app/config.py`, Settings UI |
| Tests | `tests/test_voice_routing.py`, provider-specific tests |

## Out of scope

- Social observation/perception — RFC-0053.
- Identity recognition — RFC-0054.
- Whether a spontaneous comment should be spoken — RFC-0055.
- Avatar model/animation rendering.
- Actor/character voice cloning without explicit rights.

## Notes / references

- Kokoro `hexgrad/Kokoro-82M` is an 82M open-weight model with Apache-licensed weights.
- QwenLM/Qwen3-TTS publishes 0.6B/1.7B open-source models with streaming, voice design/clone capabilities and Apache-2.0 licensing.
- Resemble AI Chatterbox is open-source/MIT at time of design; verify model-weight and dependency licenses during implementation.
