# RFC-0235: Android live local replies and model download feedback

**Status:** Proposed (pending Jarvis Architect sign-off). Specs are ratified only by the Jarvis Architect; until then this text describes the implementation in its PR and does not count toward completion.

**Author:** Codex, requested by Daan (original #650 text). Split out of #650 by the Jarvis PR fixer.

**Date:** 2026-10-17 (split 2026-10-20)

> RFC-0235 covers the streamed local replies and the model download feedback split out of #650. The solar context HUD part (planets, rings, thinking pulses, star field fading with context use, and the native context-usage counters that drive it) stays in #650 as RFC-0234 (`0234-android-solar-context-and-live-replies.md`), pending Astra's sign-off.

## Problem

Local Qwen replies on the phone look stalled, because generated tokens are buffered until generation completes. Phone-tool tasks can run ten silent inference passes. Model download screens show nothing until bytes arrive. A stalled HTTP read cannot be cancelled, and a cancelled or failed download loses its progress.

## Decision

- Stream ordinary on-device replies to Home and Chat as they are generated. Coalesce native token callbacks (at most every 80 ms) and never show an unfinished tag or internal tool JSON.
- While a reply is in progress, show the current stage and the elapsed seconds: loading the model, preparing the conversation, reading sections, reading context, writing the reply, and phone step N/10 or running a phone action.
- Log queue, load, first-token and total milliseconds for every local reply, without prompt text.
- Reuse a validated transformer prompt prefix in native llama.cpp across passes. Recurrent and hybrid models, a model change, unload, or a failed prefix removal fall back to a full reset. A cancelled or failed prefill never advertises a reusable prefix. The native log reports prompt and reused token counts.
- Publish per-model download state immediately, before the first byte. The states are connecting, downloading, retrying, verifying, ready, error and paused, with byte counts and transfer rate. Show it through shared progress feedback and per-model cards, layered on top of the existing Models screen (status line, pack dropdown, Download/Re-download, Delete, file import), the first-run setup card (Download model, Load from file), Memory & speed, and Downloaded content. Live UI is extended, never replaced.
- Pack install state, `.partial` sizes and storage are read on IO (`CompanionPackManager.packFileSnapshot`), never on the main thread or during composition.
- Cancel can interrupt a blocked HTTP read. A cancelled transfer keeps its `.partial` file and resumes with an HTTP `Range` request. Duplicate starts are prevented. A download is ready only after its checksum verifies.

## Acceptance criteria

- Ordinary local output becomes visible before generation ends; internal tool JSON stays hidden.
- Stage progress and elapsed seconds remain visible during long loads, prefill and phone actions.
- Native prefix reuse resets on model changes and fails safely; logs distinguish first-token time from total time.
- Model download feedback appears before the first byte. Retry and verification remain visibly busy, completion requires successful verification, and Cancel/Resume preserves a partial download.
- Android tests, native compilation, APK assembly and lint pass. Physical-phone speed is a separate acceptance gate; no measured on-phone speed is claimed without live timings.

## Files

CompanionModel, CompanionPackManager, LiveLocalReply, LocalInferenceEngine, jarvis_llama.cpp, MainActivity (Home live-reply line and the Models section), ModelDownloadState, ModelDownloadsUi, CompanionDeviceModelChrome, DevicePackChromePublisher, PhoneMemoryUi and DownloadedContentUi. Tests: LiveLocalReplyTest, ModelDownloadFeedbackTest, ModelDownloadsUiTest, ModelScreensLiveUiTest and PackFileSnapshotTest.

## Out of scope

- The solar HUD and context-usage display (RFC-0234 HUD part, #650).
- Desktop inference, voice synthesis redesign, and changing phone tool permissions.

## Validation

See the PR. Physical-phone first-token timings, warm-cache speedup and installation remain unverified; no phone is attached.
