# RFC-0204: Android ANZU standalone upgrade

**Status:** accepted  
**Queue item:** (none in this PR — Architect may add a §58 line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Chief of Staff (Taco authorized CoS to write this spec in parallel with the Architect, 2026-10-08)  
**Date:** 2026-10-08

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §4 (voice is a primary interface), §9 (local-first), §13 (phone companion and grid-down), §20 (quality test), §21 (finished product still works when the main PC is unavailable).  
**Amends:** [RFC-0108](0108-phone-companion-offline-ai-model.md) (edited in this PR).  
**Baseline:** [RFC-0140](0140-companion-on-device-voice-models.md) **Mode B** (grid-down / local AI). Mode A (fallback while the desktop session is up but host voice failed) stays as RFC-0140 wrote it.  
**Installer siblings (do not rewrite the installer):** display name **ANZU** with engineering ids left as Jarvis ([#567](https://github.com/Daan298261/Jarvis/pull/567)); Black Grid Publishing credit ([#568](https://github.com/Daan298261/Jarvis/pull/568)).  
**Related (do not rewrite):** [RFC-0039](0039-android-native-communications-client.md) / [RFC-0059](0059-android-companion-delivery.md) Leader remains orchestrator **when reachable**. [RFC-0074](0074-companion-pairing-streamline-and-qr.md) pairing. [RFC-0123](0123-companion-reachability-and-anti-impersonation.md) reachability and pins. [RFC-0139](0139-android-companion-fancy-orb-humanoid-ui.md) presence. [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) PC neural TTS. [RFC-0159](0159-offline-resilience-grid-down-degraded-mode.md) reconnect revalidation for consequential actions.

This PR is **specs-only**. No application code. Weights stay out of git.

## Problem

The Android companion is still a remote control that can mutter one local reply. With the desktop unreachable, `CompanionModel.sendOffline` asks a phone GGUF for 256 tokens and forbids tools. RFC-0140 Mode B already names the private loop (on-device speech in, local model, on-device speech out), and the Kotlin routing for that loop exists, but the shipping APK does not link the voice natives (`JARVIS_BUILD_VOICE_NATIVE` defaults OFF) and `jarvis_voice_tts.cpp` `nativeTtsSynthesize` returns null even when `JARVIS_VOICE_TTS_ORT` is set. The launcher label is still `Jarvis`. There is no About credit for Black Grid Publishing.

That fails the north star. The phone is supposed to stay a useful ANZU when the desktop or the network disappears (§13, §21), voice is supposed to be a real way to talk to it (§4), and a finished product does not ship a banner in place of the assistant (§20.6, §20.8). A second brain with its own memory authority would also fail (§13: one ANZU, many surfaces).

## Decision

Ship one Android app that is a capable **standalone ANZU** in **Black Grid mode**, and the same paired controller it already is when the desktop is reachable. Four product changes, two implement owners, disjoint files.

**Black Grid mode** means RFC-0140 Mode B expanded from “a local reply plus voice packs” to the capability set in §1. It is the phone operating mode used when the paired ANZU desktop (the Leader) is unreachable.

Three different “Black Grid” things stay distinct:

| Name | What it is |
| --- | --- |
| **Black Grid mode** | This RFC. Standalone ANZU on the phone. |
| **Black Grid Publishing** | Sponsor credit in §5. Same organization, different surface. |
| **Black Grid media studio** | Desktop image/video pipelines (RFC-0096 / RFC-0109). The phone must not claim those jobs are running on-device. RFC-0108’s prohibition stands. |

Online rule, unchanged from RFC-0108: when the Leader session is live, the desktop orchestrates, remembers, and runs tools. The on-device model may classify or draft only by handing off. It must not silently replace the desktop agent.

### 1. Standalone local capability (Black Grid mode)

Black Grid mode turns on when the Leader is not reachable (PC off, asleep, off-LAN, or no working WAN session). Pairing keys, TLS pins, and revocation are unchanged. Offline use does not unpair the phone and does not weaken the checks that run when the desktop returns (RFC-0074 / RFC-0123).

The owner should be able to talk to ANZU and get real work done on the phone without knowing what a Leader is. Banners say **ANZU desktop**, not “Leader”.

#### 1.1 What works offline, end to end

| Capability | Black Grid mode behavior | Done means |
| --- | --- | --- |
| **Conversation** | On-device GGUF streams tokens into the open chat. Transcript survives process death (existing snapshot + offline queue). | A question with the pack installed returns model tokens. Empty output, a canned string, or “model coming soon” is a fail. |
| **Voice turn** | Mic PCM → Whisper transcript → those tokens as the user turn → model reply → Pocket TTS playback. Typed turns stay text unless the owner asks to hear them. | Speaking a sentence and hearing the reply, with the desktop powered off. See §3. |
| **Stale desktop snapshot** | Last synced messages and tasks stay readable and are labeled as last synced, not live. | Reopening the app offline shows that history. |
| **Notes** | A note the owner types or dictates is a normal offline user turn (`origin=device_offline`) plus the assistant acknowledgement (`origin=device_local_draft`). No second note database. | The note is in the transcript and in the offline queue. |
| **Phone-local reminder** | If the owner asks to be reminded at a time this phone can parse, schedule a real `AlarmManager` alarm and a notification. Copy says the reminder is **on this phone**. Desktop schedules on More stay gated on a live session. | The notification fires. A log line is not a reminder. If notification permission is denied, say so and do not claim it was set. If the time does not parse, ask once for a time. |
| **Owner-picked text** | `ACTION_OPEN_DOCUMENT` for `text/plain` and `text/markdown`. Read up to 64 KiB into the on-device prompt and answer from it. | The answer uses the file. Larger files and non-text are refused with a reason. |
| **Camera, gallery, share sheet** | Keep the existing capture/share path. Store the bytes and queue them. The local model does not grow a vision encoder in this RFC. Tell the owner the file is saved and will be analyzed when the desktop is back. | The file is still on device after a restart, and the chat does not say it was analyzed. |
| **Pack management** | More → Models and More → Voice keep working with no network (already local files). | Download needs a network; a pack already on disk loads without one. |
| **Presence** | RFC-0139 idle / listening / thinking / speaking / offline tracks real mic, generation, and playback. | A waveform or “listening” state with no capture is a fail. |

Deterministic handling comes before the model, matching the north star’s fast path. `StandaloneMode` classifies with fixtures for the rows below. The model answers everything else. Do not send “remind me at 7” through a tool the phone does not have.

| Owner intent (fixture class) | Action |
| --- | --- |
| Reminder with a parseable local time | `LOCAL_REMINDER` |
| Reminder with no time | One question asking when. No alarm. |
| Note / “remember this” | `LOCAL_NOTE` (offline turn) |
| Open a text file I picked | `LOCAL_FILE` |
| Picture or video with no on-device vision | Store, queue, say analysis waits for the desktop |
| Send email, WhatsApp, or any external message; run HexStrike; generate an image or video; edit files on the PC; use the desktop browser, terminal, Office, or swarm | `QUEUE_OR_REFUSE` |

Generation budget for a local answer: **512** tokens while `DeviceInferenceGuard` is clear, **256** when it reports thermal or battery pressure. Unbounded generation is out. Today’s hard 256 for every turn clips ordinary answers; that cap is not the bar. An empty stream is still an error (`sendOffline` already treats blank text as failure — keep that).

`StandalonePrompt` identifies the assistant as **ANZU on this phone**, desktop unreachable, answering from the conversation, general knowledge, and any picked text. It tells the model not to claim desktop tools, studio generation, or swarm workers. Abliterated weights are there so ANZU can answer; they are not permission to invent tool results. Spoken replies stay speakable: no reading of code, URLs, or internal status (RFC-0075 spirit, on device).

#### 1.2 Graceful degradation

Desktop-only work is queued or refused in words the owner can use: **“I’ll do that when the ANZU desktop is back.”** The phone never reports that work as finished.

Queue with the existing stable ids (`request_id` / `client_message_id`, origins `device_offline` and `device_local_draft` only — `companion_offline.py` rejects other assistant origins). Ordinary chat syncs by itself.

Consequential queued actions (send, delete, pay, security, anything that leaves the house) are **not** replayed automatically on reconnect. They wait for the owner or for desktop policy (RFC-0159). A chat reply is not consequential.

Missing pieces stay honest:

| Gap | What the owner sees |
| --- | --- |
| No GGUF on disk | Install affordance. Composer does not pretend to send. |
| Pack downloading or hash failed | Progress or retry. Status never `ready` on a bad hash. |
| Abliterated pack missing, refused for RAM, or not yet published | Stock Instruct fallback (§2). Banner stays “Answering on this phone.” |
| Voice pack or native runtime missing | Text chat still works. Mic and speaker show install / error. No fake transcript, no silent WAV. |
| Thermal / low battery | Shorter answers, pause voice, say why. Do not crash-loop. |

#### 1.3 Reconnect and sync

When the desktop session is reachable again:

1. Banner: **“Desktop is back — syncing this phone’s conversation.”**
2. `POST /api/companion/sync/offline-turns` with the queued turns and stable ids (existing contract). Failure stays visible and retryable. Turns are not dropped.
3. Leader memory stays canonical. Device drafts stay labeled `device_local_draft` until the orchestrator accepts or rewrites them. Do not create a second ContextRepo on the phone.
4. Voice returns to the host path when host STT/TTS are healthy (`VoiceRouteMode.ONLINE_HOST`, RFC-0140 §5).
5. Queued attachments upload on the existing attachment path. Phone-local reminders are not re-created as desktop schedules.

### 2. On-device model

One engine: the llama.cpp JNI already in the app (`LlamaCppInferenceEngine`, native `jarvis_llama`). No second runtime.

#### 2.1 PENDING DECISION — abliterated pack name

**The abliterated model name is pending.** The project lead is sourcing it. Implementers must not choose a model, a repo, a filename, or a URL for it.

A pack may be added only when every criterion below is true:

| Criterion | Required |
| --- | --- |
| Size class | Phone-sized. Same order as the packs already shipped: about **1B–4B**, quantized **Q4_K_M** (or an equivalent the guard can justify). Larger only if `DeviceInferenceGuard` reports enough RAM. A 27B-class host profile on the phone is a fail. |
| Weights | **Abliterated / unrestricted** GGUF: the vendor refusal layer is removed. “Unrestricted” describes the weights. It does not add desktop tools, HexStrike, or filesystem rights. |
| Format and runtime | **GGUF** that `LlamaCppInferenceEngine` loads. |
| On-device behavior | Loads without a crash-loop, streams tokens, and yields to the thermal/battery guard. “Runs acceptably” is **device sign-off**. A Linux cloud VM cannot sign it off. |
| Supply | Pinned HTTPS URL, SHA-256, `size_bytes`, and filename on the RFC-0108 allowlist (phone catalog and `backend/app/mobile/companion_offline.py` together). Owner-typed URLs stay forbidden. License must allow the owner download. |
| Git | Weights are never committed. |

Until that row is real, **do not add a catalog id**. An empty `url`, a blank hash, or a “pending” placeholder row is a fail (RFC-0108 §2.1, still in force).

When the row exists, selection while the desktop is unreachable is automatic:

1. Abliterated pack installed, hash-ok, and the guard allows it → load it.
2. Else `qwen2.5-1.5b-instruct-q4` installed and allowed → load it.
3. Else the owner’s already-selected `qwen2.5-3b-instruct-q4`, if it loads.
4. Else the existing install block. No canned reply.

The owner does not have to choose “abliterated” to send a message. More → Models may show the pack label for people who open it. After the row exists, the post-pair offer prefers that pack and falls back to the 1.5B Instruct offer if it is not published yet.

#### 2.2 Stock Instruct fallback (specified now, keep working)

These #309 rows stay, including ids, filenames, URLs, hashes, and sizes. They are the **clean fallback**, not a legacy path to delete.

| id | Role | filename | size_bytes | min RAM | SHA-256 | URL |
| --- | --- | --- | --- | --- | --- | --- |
| `qwen2.5-1.5b-instruct-q4` | **Default fallback.** Recommended whenever the abliterated pack is unnamed, missing, hash-failed, or refused for RAM. | `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` | `1117320736` | 3072 MB | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` | `https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| `qwen2.5-3b-instruct-q4` | Optional larger Instruct pack when RAM allows and the owner has selected it. Not the default. | `Qwen2.5-3B-Instruct-Q4_K_M.gguf` | `2104932768` | 5120 MB | `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d` | `https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf` |

Leader cache path, first-up background download, gitignore of `*.gguf`, and the post-pair size popup stay as RFC-0108 §2.2–§2.4. The first-up download remains the **1.5B Instruct** pack until an Architect/CoS catalog edit names the abliterated file. Do not background-download an unnamed model.

### 3. Offline voice (Whisper + Pocket TTS)

RFC-0140 Mode B is the loop. This slice makes the loop real on the APK a parked implementer can resume. Do not re-platform it.

What already exists and must be reused:

| Piece | Where | State |
| --- | --- | --- |
| Mode choice | `CompanionVoiceRouting` | `GRID_DOWN_B` when the Leader is down and the local LLM is ready. Keep the table. |
| Mic capture | `CompanionModel.startOnDeviceListen` / `stopOnDeviceListen` | PCM 16 kHz mono → `CompanionVoicePackManager.transcribePcm16le` → `sendNow`. |
| STT engine | `WhisperCppSttEngine` → `VoiceNativeBridge` → `jarvis_whisper.cpp` | whisper.cpp **v1.7.5** (`voice_native/CMakeLists.txt`). Real `whisper_init` / transcribe. Fails closed when the `.so` is absent. |
| TTS engine | `PocketOrPiperTtsEngine` | Rejects empty and near-silent WAV (`isNearSilentPcmWav`). |
| TTS native | `jarvis_voice_tts.cpp` | Load checks Pocket files for engine id `pocket-tts-onnx` (`lm_main.int8.onnx`, `manifest.json`) and Piper files for `piper-onnx`. **`nativeTtsSynthesize` returns null in both `#if JARVIS_VOICE_TTS_ORT` and the `#else`.** That is the hole. |
| Build | `android/app/src/main/cpp/CMakeLists.txt` | `JARVIS_BUILD_VOICE_NATIVE` defaults **OFF**, so `jarvis_whisper` and `jarvis_voice_tts` are not in the default APK. |
| Catalog | `CompanionVoicePackCatalog` | Pinned packs, non-empty URLs, real SHA-256. Do not invent new pack ids. |

Pinned packs to keep:

| id | Role | Default? |
| --- | --- | --- |
| `whisper-tiny-en-cpp` | STT, Whisper tiny.en, ≤ ~80 MB | **Yes** |
| `whisper-base-en-cpp` | STT, better accuracy when storage allows | Optional |
| `pocket-tts-en` | TTS, Pocket TTS ONNX INT8, engine `pocket-tts-onnx` | **Yes** |
| `piper-en-lessac-medium` | TTS, small fallback if Pocket cannot load | Fallback only |

Pocket artifacts already listed on the catalog (do not drop any): `decoder.int8.onnx`, `encoder.onnx`, `lm_flow.int8.onnx`, `lm_main.int8.onnx`, `manifest.json`, `text_conditioner.onnx`, `token_scores.json`, `tokenizer.model`, `vocab.json`. Source base: `https://huggingface.co/soniqo/Pocket-TTS-100M-ONNX-INT8/resolve/v1.0.0`.

#### 3.1 Plug-in for the parked implementer

Start here. Do not rewrite Kotlin routing to “get speech working.”

1. The **release** companion ABI builds with `JARVIS_BUILD_VOICE_NATIVE=ON` so `libjarvis_whisper.so` and `libjarvis_voice_tts.so` load. Put the flag in `android/app/build.gradle.kts` `externalNativeBuild.cmake.arguments` (D1 owns that file). JVM unit tests do not need the NDK.
2. Link ONNX Runtime Mobile in `voice_native` and implement `Java_com_jarvis_companion_VoiceNativeBridge_nativeTtsSynthesize` for `pocket-tts-onnx`. Input is the pack directory already checked in `nativeTtsLoad`. Output is a PCM16 WAV with a header, loud enough to pass `isNearSilentPcmWav`. Null, empty, and silence stay failures.
3. Piper synthesis may be implemented in the same function as the small fallback. A build that only speaks with Piper does **not** meet this RFC. Pocket is the grid-down voice.
4. S1 (below) calls `speak(reply)` after a **voice** turn’s `sendOffline` when `CompanionVoiceRouting` selects `TtsVoiceRoute.ON_DEVICE`. Typed chat does not auto-speak. `speak()` already plays on-device audio; S2 must not need a second playback path.
5. Missing `.so`, missing pack, corrupt hash, or ORT init failure: the existing error strings and More → Voice download row. No canned transcript, no fake waveform.
6. While the desktop voice path is healthy, stay on gateway STT and PC neural TTS (RFC-0092 unchanged, no phone SAPI routed through the PC).

Device soak (latency, thermal, audible Pocket output) is phone sign-off. Cloud tests cover routing, catalog URL/hash rules, the near-silent reject, and “synthesize is not a stub that returns success on silence.”

### 4. User-facing ANZU rename

The product name the owner sees is **ANZU**, matching installer `MyAppName` ([#567](https://github.com/Daan298261/Jarvis/pull/567)).

**Stays Jarvis (engineering):**

- `applicationId` and `namespace`: `com.jarvis.companion`
- Package directories and class names (`JarvisApp`, `JarvisApi`, `JarvisPushService`, …)
- HTTP headers such as `X-Jarvis-Device`
- Git repository name, desktop exe names, this RFC’s repo paths

**Becomes ANZU (user-facing):**

| Surface | Change |
| --- | --- |
| Launcher / system app label | `android:label="@string/app_name"` and `app_name` = `ANZU`. This is the package display name. |
| Splash | First frame: ink `#070B12`, the existing orb `ic_jarvis` (the mark has no word in it; keep the drawable file name), and the word **ANZU**. No model load, no fake progress. Under a second, then the app. Theme lives in `styles.xml`; composable in `AnzuSplash.kt`. |
| In-app copy | Strings the owner reads: pairing, empty states, calls, notifications, LAN discovery name, errors thrown into the UI. “Jarvis is calling” → “ANZU is calling”. “Pair with Jarvis” → “Pair with ANZU”. Offline banners say “ANZU desktop”, owned by D1 in the files D1 already edits. |
| Store listing | Play Console title **ANZU**, same `applicationId`, so it is an update. The listing text is not in git. Record it as an owner step, not a code change. |

Do not rename Kotlin types to chase the brand. A class called `JarvisApi` behind a label that says ANZU matches the installer (shortcuts say ANZU; binaries stay `Jarvis.exe`).

### 5. Sponsor credit

Add an **About** block at the bottom of **More** (that screen is Settings; do not add a second settings activity).

Exact visible sentence:

`Made in the Netherlands — sponsored by Black Grid Publishing`

The dash is U+2014. Installer #568 draws the same credit as two lines, “Made in the Netherlands” and “Sponsored by Black Grid Publishing”, because the Inno wizard font must not depend on the em-dash glyph (`PlaceSponsorLine` in `installer/windows/Jarvis.iss`). On the phone the sentence is one string. The words match.

Logo: the small gold-on-black BGP mark.

- Lineage is official `Logo_black.png` (1254×1254), the file `installer/windows/assets/render_wizard_assets.py` downscales for #568.
- Do not commit the 1.1 MB original. The installer excludes it on purpose.
- Ship `android/app/src/main/res/drawable-nodpi/bgp_logo.png`.
- If the original is not on the implement machine, copy pixels from the committed render `installer/windows/assets/sponsor/bgp-logo-150.png` and show it at about 28–40dp. A redraw, a tint, or a different mark is a fail.

The logo and the sentence are one row. Tap runs `Intent.ACTION_VIEW` on `https://blackgridpublishing.com` and leaves the app for the default browser. No in-app WebView. If the device has no handler, show an error. The row is visible without scrolling past a debug panel; it sits at the end of More, which is the settings surface the owner opens.

### 6. Slices, owners, and file locks

Two owners. **D1** takes Black Grid mode and offline voice. **UX** takes the rename and the sponsor credit. Each owner may use one branch. They must not edit each other’s files. A file not listed for your slice is forbidden.

D1 sequences S1 then S2 on one branch (S2’s native work may start as soon as S1’s file list is respected; `CompanionModel.kt` is S1-only). UX sequences S3 then S4 on one branch; they share `MainActivity.kt` and may land as one PR. D1 and UX branches are parallel: their file sets are disjoint.

#### S1 — D1 — Black Grid standalone local

**Goal.** With the desktop unreachable and the Instruct pack installed, the phone is a standalone ANZU: real tokens, local notes, a real reminder, picked text, honest queues, and reconnect sync. Banners talk like a product.

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| `android/app/src/main/java/com/jarvis/companion/StandaloneMode.kt` | **New.** Intent class + degradation decision. |
| `android/app/src/main/java/com/jarvis/companion/StandalonePrompt.kt` | **New.** On-device system prompt. |
| `android/app/src/main/java/com/jarvis/companion/StandaloneActions.kt` | **New.** Notes, reminder scheduling, SAF text cap, queue/refuse copy. |
| `android/app/src/test/java/com/jarvis/companion/StandaloneModeTest.kt` | **New.** Fixture matrix for §1.1. |
| `CompanionModel.kt` | `sendOffline`, prompt, voice-turn `speak(reply)`, sync, user-visible “Jarvis” strings **in this file**. |
| `CompanionRouting.kt`, `CompanionRoutingTest.kt` | Offline reason copy says ANZU. Routing modes stay. |
| `CompanionPackCatalog.kt`, `CompanionPackCatalogTest.kt` | Instruct rows unchanged. Abliterated row only after §2.1 is decided. |
| `CompanionPackManager.kt` | Automatic fallback order in §2.1. |
| `LocalInferenceEngine.kt`, `LlamaCppInferenceEngine.kt`, `DeviceInferenceGuard.kt` | Budget 512/256. No new engine. |
| `CompanionOfflineHooks.kt`, `CompanionOfflineStatus.kt` | Banner copy: “ANZU desktop” / “Answering on this phone.” |
| `DevicePackChromePublisher.kt`, `OutboxQueue.kt` | Only if a status or queue field is required. Schema origins stay. |
| `PostPairOfflinePackOffer.kt` | Only after the abliterated row exists. Until then, leave the Instruct offer. |
| `backend/app/mobile/companion_offline.py` and `tests/test_rfc0108_companion_sync.py` | **Only** when the pending pack is named. Until then, do not touch. Empty URL remains a test failure. |

**Acceptance.**

- [ ] Desktop unreachable + 1.5B Instruct pack installed → a chat turn returns real tokens (unit test with the scripted engine; live GGUF is device sign-off).
- [ ] Blank model output is an error, not a bubble.
- [ ] Fixture tests: reminder with a time schedules; reminder without a time asks; note lands in the offline queue; desktop-only intents queue or refuse and are not marked done; consequential queues do not auto-replay.
- [ ] Picked text over 64 KiB is refused; under the cap it is in the prompt.
- [ ] Image capture does not claim analysis.
- [ ] Reconnect calls `sync/offline-turns` with stable ids and the existing origins.
- [ ] No catalog row for an unnamed model. Instruct ids, URLs, and hashes unchanged.
- [ ] Fallback order is abliterated (if a legal row exists and loads) then 1.5B Instruct then selected 3B.
- [ ] After a voice turn, `speak(reply)` runs when TTS route is `ON_DEVICE`.
- [ ] User-visible strings **in S1 files** say ANZU, not Jarvis. “Leader” is gone from owner-facing banners.
- [ ] Android unit tests for the new matrix pass. `python3 -m pytest` passes if backend files changed; if they did not, do not churn them.

**Depends on.** Nothing for the Instruct path. The abliterated catalog row depends on the open question in §8. Audible speech depends on S2; the `speak` call itself is S1.

#### S2 — D1 — Offline voice

**Goal.** Grid-down speech is Whisper in and Pocket TTS out, on the APK, failing closed when a piece is missing.

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| `android/app/src/main/cpp/CMakeLists.txt` | Voice native included on the shipping APK. |
| `android/app/src/main/cpp/voice_native/**` | Whisper fetch stays; ORT link lives here. |
| `android/app/src/main/cpp/jarvis_whisper.cpp` | Keep real transcribe; fix only if the device path is wrong. |
| `android/app/src/main/cpp/jarvis_voice_tts.cpp` | **Plug-in.** `nativeTtsSynthesize` produces Pocket WAV. |
| `android/app/build.gradle.kts` | Cmake argument `JARVIS_BUILD_VOICE_NATIVE=ON` only. Do not change `applicationId`, `namespace`, or version. |
| `OnDeviceVoiceEngines.kt` | Keep the silent-audio reject. |
| `CompanionVoicePackManager.kt`, `CompanionVoicePackCatalog.kt`, `CompanionVoicePackStatus.kt`, `CompanionVoiceRouting.kt`, `DeviceVoiceGuard.kt` | Behavior fixes only. Do not replace the route table or the pack ids. |
| `CompanionVoicePackManagerTest.kt`, `CompanionVoicePackCatalogTest.kt` | Catalog and fail-closed tests. |
| `PostPairVoicePackOffer.kt` | Only if the offer must mention Pocket by the existing label. |

**Does not open:** `CompanionModel.kt` (S1 owns the `speak` call), any UX file, `companion_offline.py`.

**Acceptance.**

- [ ] Release native build defines `JARVIS_BUILD_VOICE_NATIVE` so both voice libraries are linked. A missing library still fails closed in `VoiceNativeBridge`.
- [ ] `nativeTtsSynthesize` for `pocket-tts-onnx` returns a non-silent WAV for a short English sentence on device. Null success is a fail.
- [ ] Whisper tiny.en returns a transcript for a real PCM buffer on device. A hardcoded transcript is a fail.
- [ ] Mode B fixture: Leader down, LLM ready, both packs ready → `GRID_DOWN_B` + on-device STT + on-device TTS (existing routing test, kept).
- [ ] Leader up and host voice healthy → host path, unchanged.
- [ ] Piper is not the default success path.
- [ ] RFC-0092 / PC SAPI untouched.
- [ ] JVM tests pass without a phone. Live audio is device sign-off, called out in the implement PR.

**Depends on.** S1 for the spoken reply after `sendOffline`. Native Pocket work does not depend on S1 and must not wait on the model-name decision.

#### S3 — UX — ANZU rename

**Goal.** Every owner-facing label in UX files says ANZU. Engineering ids stay.

**Owns (exclusive):**

| Path | Why |
| --- | --- |
| `android/app/src/main/AndroidManifest.xml` | `android:label="@string/app_name"`. |
| `android/app/src/main/res/values/strings.xml` | **New.** `app_name` = `ANZU`, plus strings moved out of UX Kotlin. |
| `android/app/src/main/res/values/styles.xml` | Splash theme, ink `#070B12`. |
| `android/app/src/main/res/drawable/ic_jarvis.xml` | Read-only. Do not redraw. |
| `android/app/src/main/java/com/jarvis/companion/AnzuSplash.kt` | **New.** Wordmark ANZU + existing orb, then dismiss. |
| `android/app/src/main/java/com/jarvis/companion/AnzuBranding.kt` | **New.** `DISPLAY_NAME = "ANZU"` for the splash and any UX code. |
| `android/app/src/main/java/com/jarvis/companion/MainActivity.kt` | Owner-facing “Jarvis” strings. Do not change offline routing behavior. |
| `Calls.kt` | Notification and call titles. |
| `JarvisApi.kt` | Exception text the UI shows. Leave `X-Jarvis-Device` and the class name. |
| `LanBeacon.kt`, `LanBeaconTest.kt` | Discovery name default `ANZU`. Update the test. |
| `CompanionPairingQr.kt` | The one owner-facing error. |
| `RealtimeVoiceSession.kt` | Owner-facing error text only. |
| `android/app/src/test/java/com/jarvis/companion/AnzuBrandingTest.kt` | **New.** Display name is `ANZU`. |

**Acceptance.**

- [ ] Installed launcher label is ANZU (`app_name`).
- [ ] `applicationId` and `namespace` are still `com.jarvis.companion`. Diff does not touch them.
- [ ] Splash shows ANZU and the existing orb, and does not block on a model.
- [ ] UX-owned Kotlin no longer shows the product name Jarvis. Class names may.
- [ ] `AnzuBrandingTest` and `LanBeaconTest` pass.
- [ ] No edits under `cpp/`, `CompanionModel.kt`, pack catalogs, or backend.

**Depends on.** Nothing. Lands in parallel with D1.

#### S4 — UX — Black Grid Publishing credit

**Goal.** About on More shows the sponsor sentence and the real mark, and the tap opens the site in the default browser.

**Owns (exclusive, shared with S3 because one UX owner):**

| Path | Why |
| --- | --- |
| `android/app/src/main/java/com/jarvis/companion/SponsorCredit.kt` | **New.** Row composable + `ACTION_VIEW`. |
| `android/app/src/main/res/drawable-nodpi/bgp_logo.png` | **New.** Downscale of `Logo_black.png` / copy of `bgp-logo-150.png`. |
| `AnzuBranding.kt` | Add `SPONSOR_CREDIT` and `SPONSOR_URL` next to the display name. |
| `MainActivity.kt` | One call at the bottom of `MoreScreen`. |
| `android/app/src/test/java/com/jarvis/companion/SponsorCreditTest.kt` | **New.** Exact sentence and URL. |

**Acceptance.**

- [ ] More → About shows `Made in the Netherlands — sponsored by Black Grid Publishing` (U+2014) and the gold-on-black mark.
- [ ] Tap builds an `ACTION_VIEW` for `https://blackgridpublishing.com` (unit test the intent; a device check opens the browser).
- [ ] No WebView. No substitute logo. The 1.1 MB original is not added to git.
- [ ] `SponsorCreditTest` passes.

**Depends on.** S3 only because both edit `MainActivity.kt` and `AnzuBranding.kt`. Same UX branch. No dependency on D1.

## Acceptance criteria

The RFC is met when every slice’s boxes are checked. This list is the product bar, tied to the north star (one assistant, real when the desktop is gone, no stub that merely looks wired).

- [ ] Specs-only in **this** PR: `docs/rfcs/0204-android-anzu-standalone-upgrade.md`, the RFC-0108 amendment, and the RFC index line. No `android/`, `backend/`, or `frontend/` product edits.
- [ ] Black Grid mode, desktop unreachable, Instruct pack present: the owner gets a real on-device answer, can leave a note, can set a phone reminder that fires, and can ask about a picked text file.
- [ ] Desktop-only work is queued or refused in plain language and is not reported as done. Consequential queues wait for a human or desktop policy on reconnect.
- [ ] Reconnect syncs ordinary turns with stable ids. One memory authority.
- [ ] Abliterated pack is used automatically once it meets §2.1. Until the name exists, no placeholder catalog row. Instruct 1.5B remains the fallback and still generates tokens.
- [ ] Voice turn offline: Whisper transcript → model tokens → audible Pocket TTS. Missing pieces fail closed.
- [ ] Online desktop session still orchestrates, and healthy host voice still wins.
- [ ] Launcher label ANZU. `applicationId` `com.jarvis.companion`. Repo name unchanged.
- [ ] About shows the exact sponsor sentence and mark; tap opens `https://blackgridpublishing.com` in the default browser.
- [ ] D1 and UX implement PRs do not edit the same files (lists in §6).
- [ ] Implement PRs do not edit Architect spec docs. Live GGUF, Whisper, and Pocket audio are device sign-off, written as such in those PRs.

## Likely files

The slice tables in §6 are the contract. Summary:

| Owner | Paths |
| --- | --- |
| D1 | `Standalone*.kt`, companion model/routing/pack/offline/voice Kotlin listed in S1 and S2, `android/app/src/main/cpp/**` voice files, `android/app/build.gradle.kts` cmake argument only, backend catalog only after the model is named |
| UX | Manifest label, `strings.xml`, `styles.xml`, `AnzuSplash.kt`, `AnzuBranding.kt`, `SponsorCredit.kt`, `bgp_logo.png`, `MainActivity.kt`, `Calls.kt`, `JarvisApi.kt` strings, `LanBeacon.kt`, `CompanionPairingQr.kt`, `RealtimeVoiceSession.kt` strings, UX tests |
| Neither in this PR | `frontend/`, installer scripts, `JARVIS_MASTER_PLAN.md`, other Architect specs |

## Out of scope

- Choosing the abliterated model (open question, §8).
- A second memory store, a phone swarm node, or HexStrike on device (RFC-0032 / RFC-0105).
- On-device vision or image generation. Black Grid media studio stays on the desktop.
- Rewriting RFC-0092, desktop Kokoro, or the installer (name and credit already landed in #567 / #568).
- Renaming packages, classes, the git repo, or `Jarvis.exe`.
- Play Console listing copy (owner step, named in §4).
- Persona roster changes (RFC-0137) and presence art (RFC-0139) beyond using the states already shipped.
- Multilingual voice packs. English-first, as RFC-0140.

## Risks and open questions

1. **PENDING — abliterated model name.** Project lead is sourcing it. Criteria are §2.1. Do not guess a Hugging Face repo. Instruct fallback is the shippable brain until the row is filled in a follow-up catalog edit (same allowlist rules, no empty URL).
2. **Pocket TTS native is the known hole.** `nativeTtsSynthesize` returns null with and without `JARVIS_VOICE_TTS_ORT`. S2 exists to close that, not to redesign voice. ORT Mobile packaging (ABI size, license of the runtime) must be checked while linking; a compile flag that still returns null is a fail.
3. **Device sign-off.** Cloud agents have no phone and no GPU. Token streaming, Whisper accuracy, Pocket loudness, alarm delivery, and thermal behavior are unverified until a device pass. Implement PRs say so.
4. **RAM and thermals.** An abliterated GGUF that misses the 1B–4B class will be refused by the guard and must fall back to Instruct, not crash. If the lead’s candidate cannot do that, it fails §2.1 and stays out of the catalog.
5. **“Unrestricted” misread.** Abliterated weights remove the vendor refusal layer. They do not authorize desktop tools. S1 tests lock the queue/refuse matrix so a compliant model cannot mark a desktop action done.
6. **File-lock drift.** `MainActivity.kt` is UX-only and `CompanionModel.kt` is D1-only. A “small” cross-edit will conflict. New UI for standalone behavior goes through state D1 already publishes (`activity`, offline banner, errors), which MainActivity already renders.
7. **Play listing vs in-app name.** The launcher label ships in the APK. The store title does not. Both should read ANZU; only the label is a code acceptance check.
8. **Reminder exactness.** Exact alarms may need `SCHEDULE_EXACT_ALARM` on newer Android. If the permission is denied, use an inexact alarm and say the time may move. Do not skip the notification.
9. **Banner copy split across owners.** D1 rewrites banners in `CompanionOfflineStatus.kt`. UX rewrites chrome in `MainActivity.kt`. Both must say ANZU. Neither edits the other’s file to “finish” the rename.

## Notes

- North star gate: a phone that only shows “desktop offline” is not ANZU. Black Grid mode is the same assistant, fewer tools, still honest.
- RFC-0108 amendment (2026-10-08) is in this PR: Instruct-only is revised; the §3 must-not list allows the abliterated weights and keeps the tool prohibitions.
- Implement launch, after this merges: one D1 PR for S1+S2 (`cursor/<slug>-…` from `development`) and one UX PR for S3+S4. Do not edit Architect specs in those PRs. Do not merge unrelated PRs.
- Linux cloud cannot sign off on-device GGUF, Whisper, or Pocket audio.
