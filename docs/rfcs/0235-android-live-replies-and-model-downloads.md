# RFC-0235: Android live local replies and model download feedback

**Status:** Proposed (pending Jarvis Architect sign-off). Specs are ratified only by the Jarvis Architect; until then this text describes the implementation in its PR and does not count toward completion.

**Author:** Codex, requested by Daan (original #650 text). Split out of #650 by the Jarvis PR fixer.

**Date:** 2026-10-17 (split 2026-10-20); amended 2026-11-03 by the Jarvis Architect (UX's #671 review item 6 and CoS's ruling on item 1; traced on #671 @ `8b30a715`; load and turn-cap deadlines added the same day on CoS's pin of item 6)

**Amended 2026-11-03 (Architect):** the spec now describes everything #671 ships: the stall deadlines and typed error, the turn lifecycle (stage ticker with the memory-pressure warning, cleanup, cancel and failure), the Home status lines, side-effect-free pack selection and the download entry points. Each has acceptance criteria and names the tests #671 already has at their real paths; tests the spec needs and #671 lacks are listed in *Tests the spec needs that #671 does not have yet* (they are named, not written, and nothing here claims they pass). **CoS ruling on UX item 1:** a failed turn keeps its error bubble in Chat (add-only); only the partial reply and the Home preview are cleared. *Where the code at `8b30a715` does not yet meet this text* is listed in its own section. Citations are by file and symbol, never by line.

**Amended 2026-11-10 (Architect):** UX verified the #671 gaps closed; each was checked against the code at #671's head on 2026-11-10. Criteria A to F are ticked with the symbol or test that meets them, the tests formerly listed as missing are present (*Tests the spec added to #671*), and the gap list records each gap as closed. One item stays open: the CoS ruling that the 300 s cap starts when the turn starts and covers the whole turn (gap 7). The two renamed tests are `idleStallRaisesTypedErrorAndStopsDecode` and `failedStreamDropsThePartialAndKeepsTheErrorBubble`.

> RFC-0235 covers the streamed local replies and the model download feedback split out of #650. The solar context HUD part (planets, rings, thinking pulses, star field fading with context use, and the native context-usage counters that drive it) stays in #650 as RFC-0234 (`0234-android-solar-context-and-live-replies.md`), pending Astra's sign-off.

## Problem

Local Qwen replies on the phone look stalled, because generated tokens are buffered until generation completes. Phone-tool tasks can run ten silent inference passes. Model download screens show nothing until bytes arrive. A stalled HTTP read cannot be cancelled, and a cancelled or failed download loses its progress.

## Decision

- Stream ordinary on-device replies to Home and Chat as they are generated. Coalesce native token callbacks (at most every 80 ms) and never show an unfinished tag or internal tool JSON.
- While a reply is in progress, show the current stage and the elapsed seconds: loading the model, preparing the conversation, reading sections, reading context, writing the reply, and phone step N/10 or running a phone action.
- Log queue, load, first-token and total milliseconds for every local reply, without prompt text.
- Reuse a validated transformer prompt prefix in native llama.cpp across passes. Recurrent and hybrid models, a model change, unload, or a failed prefix removal fall back to a full reset. A cancelled or failed prefill never advertises a reusable prefix. The native log reports prompt and reused token counts.
- Publish per-model download state immediately, before the first byte. The states are connecting, downloading, retrying, verifying, ready, error and paused, with byte counts and transfer rate. Show it through shared progress feedback and per-model cards, layered on top of the existing Models screen (status line, pack dropdown, Download/Re-download, Delete, file import), the first-run setup card (Download model, Load from file), Memory & speed, and Downloaded content. Live UI is extended, never replaced (including the failed-turn error bubble, see the ruling in *Turn lifecycle*).
- Pack install state, `.partial` sizes and storage are read on IO (`CompanionPackManager.packFileSnapshot`), never on the main thread or during composition.
- Cancel can interrupt a blocked HTTP read. A cancelled transfer keeps its `.partial` file and resumes with an HTTP `Range` request. Duplicate starts are prevented. A download is ready only after its checksum verifies.

### Stall deadlines and the typed error (`LocalStreamStall.kt`, `CompanionPackManager.watchedGenerate`)

- A local turn runs under four deadlines (CoS pinned UX item 6 on 2026-11-03): **180 s load phase** and **300 s overall turn cap** (below), and, for every native generation pass, **120 s to the first token** (`LocalStallDeadlines.firstTokenMs`, measured from the start of the pass, prefill included) and **30 s idle** (`idleMs`, the longest gap between two tokens). The four budgets are `LocalStallDeadlines.firstTokenMs`, `idleMs`, **`loadMs` (default 180 000)** and **`turnMs` (default 300 000)**; `init` rejects non-positive values, and all four are injectable together with the clock for tests.
- **Load phase, 180 s.** Measured from the start of the model load until the engine is ready to generate (model loaded, context created, ready for the first `generate`). If it is not ready by then the load is stopped (`engine.requestCancel()` plus unload) and the turn ends with the typed error with `deadline = load`. A load that never returns control to the watchdog is the native-side gap already disclosed in the PR; the deadline still fails the turn as soon as control returns.
- **Overall turn cap, 300 s.** Measured from the start of the turn (the moment `LocalReplyTurn` opens) and covering **every pass of the turn**: the load, each section-summary pass and the reply pass. No pass may run past the cap: each pass's watchdog also enforces the time left on the turn, so the first of first-token, idle, load and turn limits to expire ends the turn. When the cap ends it, the typed error carries `deadline = turn`, and `elapsedMs` and `budgetMs` are the turn's elapsed time and 300 000.
- A watchdog (`watchedGenerate`) runs on `Dispatchers.Default`, off the llama thread, which is blocked in native decode. It polls every `checkEveryMs` (a quarter of the shorter deadline, clamped to 10 ms to 1 s). On a stall it logs `local_reply_stall` (model, deadline, elapsed, budget; no prompt text), calls `engine.requestCancel()` and the pass ends with a **typed error**, `LocalStreamStallError(deadline, elapsedMs, budgetMs, model)`, where `deadline` is `first_token`, `idle`, **`load`** or **`turn`** (a fourth and a fifth constant beside `FIRST_TOKEN` and `IDLE`; the code's existing `deadline` string is extended, so there is no new class). The text names the deadline, the elapsed and limit seconds and the model, says the model was stopped, and suggests trying again or choosing a smaller model; for `load` it says the model did not finish loading, and for `turn` that the whole reply took too long.
- The deadlines cover the reply pass **and every section-summary pass** of a sectioned prompt (`summarizeSections` also goes through `watchedGenerate`). The first-token and idle budgets are per pass; the turn cap spans all passes, so a sectioned prompt cannot run longer than 300 s however many passes it has.
- **All four deadlines take the same failure path.** The stall is **not a cancellation**: it is an ordinary failure of the turn. The turn therefore fails visibly (see the failed-turn ruling), runs cleanup (`unload()` resets a `RUNNING` pack to `READY`) and **releases the send lock** (`CompanionModel.sendLock`), so the next message can be sent. A cancellation by the owner is still a cancellation and rethrows.
- A stall never sets `localPackError` and never marks the pack `ERROR`: the model is fine, the pass was stopped.

### Turn lifecycle: ticker, cleanup, cancel and failure (`LocalReplyTurn.kt`, `GenerateOutcome.kt::withOfflineAnswerCleanup`)

- **Stage ticker.** `LocalReplyTurn` owns the UI state of one on-device reply. While the turn is open a ticker (every 1 s, in `viewModelScope`) writes `activity` as `[memory-pressure warning ·] stage · Ns`, with the stage set through `progress(...)` (loading the model, preparing the conversation, reading sections, reading context, writing the reply, `Phone step N/10 · ...`, `Running phone action N/10`) and N the elapsed seconds. **A memory-pressure warning is never hidden:** once `pressure(reason)` has been called, every tick starts with that reason. `CompanionModel.refresh` leaves `activity` and `messages` alone while `offlineAnswering` is true, so a desktop poll cannot overwrite the stage line or the streamed bubble, and the "desktop is back" banner is not shown during a local answer.
- **Streamed preview.** The coalesced token sink (`LiveLocalReply`, at most every 80 ms, no unfinished tag, no tool JSON) publishes the partial to `liveLocalReply` (Home) and as the pending last assistant message in `messages` (Chat).
- **Cleanup (`withOfflineAnswerCleanup`).** However the turn ends: `clearPicked()` runs; the engine is unloaded unless the turn succeeded **and** `keepWarm()` holds (`keepModelWarm` on, app in the foreground, no memory pressure); the ticker is cancelled; the turn's `onFinally` runs. A successful keep-warm turn schedules a 30 s idle unload. A cancellation rethrows after cleanup; any other exception becomes `Result.failure`.
- **Landed turn.** The reply is saved to the local conversation and the offline queue, `landed()` puts the saved assistant message in `messages` and clears `liveLocalReply` (Home no longer needs the preview).
- **Failed, stalled or cancelled turn: ruling (CoS, UX item 1).** *A failed turn keeps its error bubble (add-only); only the partial reply and the Home preview are cleared.*
  - On **failure or stall**, `messages` ends as `prior + <error bubble>`: an assistant message carrying the error text, exactly as before this PR (development's `sendOffline` always ended with `prior + assistantMessage`, the message carrying the error text). The bubble is **unsaved**: it is not written to the local conversation and not appended to the offline queue, so it disappears on reload, never syncs to the desktop and never becomes a reply. `error` is also set (Home presence input and Offgrid error text), as before.
  - The **partial streamed text** is removed from `messages` (it is replaced by the error bubble, never shown next to it) and `liveLocalReply` is cleared. Home shows no preview of a failed turn.
  - On **cancellation** nothing is left: `messages = prior`, `liveLocalReply = ""`, `error` unchanged (the owner stopped it; there is no error to show).
  - Live UI is extended, never replaced: the failed-turn bubble is an existing behaviour and stays.
- Starting or opening another conversation clears `liveLocalReply`.

### Home status lines and download entry points (`CompanionModel.installFastPhoneModel`, `downloadModelPack`)

- Memory & speed's fast-model download keeps its two Home status lines, alongside the transfer card: **`Downloading fast phone model · N%`** on every progress step (also `localPackProgress`), and **`Fast phone model ready`** when the download verified and finished. `installFastPhoneModel` is `downloadModelPack(ABLITERATED_06B_ID, onProgress, onReady)`.
- `downloadModelPack(packId, onProgress, onReady)` is the single, non-blocking entry point for every download (setup card, Models screen, library cards, Downloaded content, the fast-model button, retry from a notification): it launches in `viewModelScope`, ignores a pack that is already downloading, calls `packManager.downloadPack`, rethrows cancellation, and always refreshes `modelDownloads`, `localPackStatus`, `localPackProgress` and `localPackError` in `finally`. `downloadCompanionPack()` downloads the selected pack through it.
- **Busy and error semantics are kept from development's `action {}` wrapper:** a download sets `error = null` when it starts, sets `error` to the message on a non-cancel failure (so a failed download still reaches the Home presence `hardError` input and the Offgrid error text), and counts as `busy` while it runs (the fast-model button and notification retry actions stay disabled). Several concurrent downloads keep `busy` true until the last ends (a counter of active downloads).

### Pack selection (`CompanionModel.selectCompanionPack`)

- Picking a pack in the dropdown is **side-effect free**: it selects the pack, then refreshes the pack status and publishes the device chrome (`publishSelectedPack`: `refreshStatus`, `localPackStatus`, `localPackError`, `DevicePackChromePublisher.publish`, which reads pack files on IO through `packFileSnapshot`). It does **not** mark the screen `busy` and does **not** clear a visible `error`.

## Acceptance criteria

- Ordinary local output becomes visible before generation ends; internal tool JSON stays hidden.
- Stage progress and elapsed seconds remain visible during long loads, prefill and phone actions.
- Native prefix reuse resets on model changes and fails safely; logs distinguish first-token time from total time.
- Model download feedback appears before the first byte. Retry and verification remain visibly busy, completion requires successful verification, and Cancel/Resume preserves a partial download.
- The per-feature criteria A to F below are met, and every test they name exists and passes.
- Android tests, native compilation, APK assembly and lint pass. Physical-phone speed is a separate acceptance gate; no measured on-phone speed is claimed without live timings.

### Acceptance criteria per feature (tests are named in the next section)

**A. Stall deadlines.**
- [x] The default deadlines are 120 s to the first token, 30 s idle, 180 s load phase and 300 s overall turn cap, and non-positive values are rejected. *Met:* `defaultStallDeadlinesAre120s30s180sAnd300s`, `nonPositiveStallDeadlineIsRejected`.
- [x] A model load that is not ready to generate 180 s after it started ends the turn with `LocalStreamStallError(load)`, the load is stopped, and the pack is unloaded. *Met:* `loadPhaseDeadlineIs180sAndRaisesTypedError`, `CompanionModelOffgridTurnTest.loadDeadlineThroughSendOffgridRaisesTheTypedErrorAndReleasesTheLock`.
- [ ] A turn still running 300 s after it started ends with `LocalStreamStallError(turn)`, including when no single pass is stalled: for a sectioned prompt the cap is shared by all summary passes and the reply pass. *Open (CoS ruling, the spec stands; the code follows):* the cap must start when `LocalReplyTurn` opens and cover the whole turn. At the branch head `CompanionPackManager.TurnGuard` starts its clock per `CompanionPackManager.generate` call, so the cap covers one call (its load, summary passes and reply pass, as `overallTurnCapIs300sAcrossSummaryPasses` and `overallTurnCapThroughSendOffgridRaisesTheTypedErrorAndReleasesTheRealSendLock` prove) but not the time before it, and each `generate` of the phone-tool loop in `phoneLocalAnswer` gets its own 300 s.
- [x] Load and turn-cap stalls take the same failure path as first-token and idle stalls: the error bubble per the ruling, the real `sendLock` released, the same cleanup. *Met:* `loadAndTurnCapStallsFailTheTurnLikeAnyOtherStall`, `CompanionModelOffgridTurnTest.loadDeadlineThroughSendOffgridRaisesTheTypedErrorAndReleasesTheLock` and `overallTurnCapThroughSendOffgridRaisesTheTypedErrorAndReleasesTheRealSendLock`.
- [x] A pass that streams a partial and then goes quiet ends with `LocalStreamStallError(idle)` after the idle budget, native decode is asked to stop, and the turn returns a failure (not a cancellation). *Met:* `idleStallRaisesTypedErrorAndStopsDecode`.
- [x] A pass that never produces a token ends with `LocalStreamStallError(first_token)` after its budget. *Met:* `firstTokenStallRaisesTypedError`.
- [x] A steady stream under both deadlines is never a stall. *Met:* `steadyStreamUnderTheDeadlinesIsNotAStall`.
- [x] A stall in a section-summary pass fails the turn the same way. *Met:* `sectionSummaryPassStallRaisesTypedError`.
- [x] After a stall the real `CompanionModel.sendLock` is released (the next `sendOffgrid` runs), the engine is unloaded and a `RUNNING` pack is `READY` again; `localPackError` stays empty. *Met:* `CompanionModelOffgridTurnTest.stallThroughSendOffgridReleasesTheRealSendLock`, `stalledTurnUnloadsTheEngineAndLeavesPackReadyWithNoPackError`.

**B. Stage ticker and memory-pressure warning.**
- [x] The ticker shows stage and elapsed seconds on every tick; with a pressure reason set, every tick starts with it, in the chat path and in the phone-tool path. *Met:* `stageTickerKeepsTheMemoryPressureWarningVisible`, `stageTickerWithoutPressureShowsStageAndElapsed`, `CompanionModelOffgridTurnTest.phoneToolPassesShowTheMemoryPressureWarning`.
- [x] A desktop poll during a local answer changes neither `activity` nor `messages`. *Met:* `CompanionModelOffgridTurnTest.desktopPollDuringALocalAnswerLeavesActivityAndMessagesAlone`.

**C. Cleanup.**
- [x] After success, failure, stall or cancellation, the picked text is cleared and the ticker is cancelled. *Met:* `StandaloneModeTest.errorMidAnswerUnloadsAndClearsPicked`, `cancelledTurnUnloadsTheEngineAndClearsPicked`.
- [x] The engine is unloaded after failure, stall and cancellation, and after success unless keep-warm holds; a keep-warm success schedules the 30 s idle unload. *Met:* `stalledTurnUnloadsTheEngineAndLeavesPackReadyWithNoPackError`, `cancelledTurnUnloadsTheEngineAndClearsPicked`, `keepWarmKeepsTheModelOnlyAfterASuccessfulTurn`.

**D. Failed and cancelled turns (CoS ruling).**
- [x] After a failure or stall, `messages` is `prior` plus one unsaved error bubble carrying the error text, the partial reply is in no message, `liveLocalReply` is empty and `error` is set. *Met:* `failedTurnKeepsItsErrorBubbleAndClearsOnlyThePartialAndHomePreview` (`LocalReplyTurnTest`, and through `sendOffgrid` in `CompanionModelOffgridTurnTest`), `failedStreamDropsThePartialAndKeepsTheErrorBubble`; code: `LocalReplyTurn.failed`.
- [x] The error bubble is not in the local conversation store and not in the offline queue. *Met:* `CompanionModelOffgridTurnTest.failedTurnErrorBubbleIsNeverSavedOrQueued`.
- [x] After a cancellation, `messages` is `prior`, `liveLocalReply` is empty and `error` is unchanged. *Met:* `cancelledStreamLeavesNoPartialReplyInChatOrOnHome`, `CompanionModelOffgridTurnTest.cancelledTurnLeavesNoPartialAndNoErrorAndReleasesTheLock`.
- [x] After a landed reply, `messages` is `prior` plus the saved reply and `liveLocalReply` is empty, through `sendOffline` itself. *Met:* `CompanionModelOffgridTurnTest.sendOffgridLandsTheReplyAndClearsTheHomePreview`.

**E. Home.**
- [x] The streamed reply appears once on Home: while `liveLocalReply` is not blank the existing last-assistant line is not rendered (it would show the same text a second time); when it is blank the existing line renders exactly as before. *Met:* `HomeLiveReplyUiTest.homeShowsTheStreamedReplyOnce`.
- [x] `Downloading fast phone model · N%` and `Fast phone model ready` appear in `activity` for the fast-model download, and the Memory & speed card shows the transfer view and the ready line. *Met:* `CompanionModelDownloadTest.installFastPhoneModelPublishesTheHomeStatusLines`, `PhoneMemoryUiTest.memorySpeedFastModelSectionShowsTransferAndReadyLine`.

**F. Downloads and pack selection.**
- [x] A failed download sets `error`, a retry clears it, and the fast-model button is disabled while its download runs. *Met:* `CompanionModelDownloadTest.failedDownloadSetsErrorAndRetryClearsIt`, `fastModelButtonIsDisabledWhileItsDownloadRuns`.
- [x] `selectCompanionPack` leaves `error` and `busy` as they were and publishes the new selection. *Met:* `CompanionModelDownloadTest.selectCompanionPackLeavesErrorAndBusyUntouched`.
- [x] A download shows one determinate bar per card: while the legacy status-card bar is visible for the selected pack, that pack's "All models" card shows no second bar (its own bar is shown for any other pack). *Met:* `ModelScreensLiveUiTest.libraryCardShowsNoSecondBarForTheSelectedPackWhileTheLegacyBarIsVisible`.
- [x] Downloaded content lists each non-ready transfer with Cancel/Resume. *Met:* `DownloadedContentUiTest.downloadedContentShowsModelTransferRows`.

### Tests #671 already has (all under `android/app/src/test/java/com/jarvis/companion/`)

| Area | Test (file) |
| --- | --- |
| A | `idleStallRaisesTypedErrorAndStopsDecode`, `firstTokenStallRaisesTypedError`, `steadyStreamUnderTheDeadlinesIsNotAStall` (`LocalReplyTurnTest.kt`); the idle stall's lock release is asserted against the real `CompanionModel.sendLock` in `CompanionModelOffgridTurnTest.stallThroughSendOffgridReleasesTheRealSendLock` |
| B | `stageTickerKeepsTheMemoryPressureWarningVisible`, `stageTickerWithoutPressureShowsStageAndElapsed` (`LocalReplyTurnTest.kt`) |
| C | `errorMidAnswerUnloadsAndClearsPicked` (`StandaloneModeTest.kt`, failure only) |
| D | `cancelledStreamLeavesNoPartialReplyInChatOrOnHome`, `landedReplyClearsTheHomePreviewAndStaysInChat` (calls `turn.landed()` by hand), `failedStreamDropsThePartialAndKeepsTheErrorBubble` (`LocalReplyTurnTest.kt`; asserts the ruling: `messages` is `prior` plus one assistant error bubble carrying the error text, and `liveLocalReply` is empty) |
| streaming | `publishesFirstTokenBeforeCompletionAndCoalescesLaterTokens`, `splitReasoningAndTemplateMarkersNeverLeak` (`LiveLocalReplyTest.kt`) |
| F (transfers) | `connectingIsVisibleBeforeHeadersAndCancellationUnblocksNetwork`, `partialDownloadCanResumeAndOnlyBecomesReadyAfterVerification`, `checksumFailureIsAnInlineErrorAndNeverReady`, `transientServerFailureShowsRetryAndRecovers` (`ModelDownloadFeedbackTest.kt`); `downloadHasImmediateFeedbackAndCanBePausedAndResumed`, `renderModelCardsWithDownloadProgress` (`ModelDownloadsUiTest.kt`) |
| F (live UI kept) | `modelsScreenKeepsStatusDropdownAndRedownloadWithProgressOnTop`, `setupCardKeepsDownloadButtonWhileShowingTransferFeedback`, `legacyProgressStaysVisibleDuringATrackedDownload`, `modelsCardKeepsLegacyPercentDuringATrackedDownload` (`ModelScreensLiveUiTest.kt`; the last one now asserts the legacy percent text on both cards and no second bar, criterion F) |
| F (files off main) | `snapshotReadsPackFilesOnTheFileDispatcherNotTheMainThread`, `chromeStateTakesFileFactsFromTheSnapshotWithoutTouchingDisk` (`PackFileSnapshotTest.kt`) |

### Tests the spec added to #671: 24 tests in 20 rows (all present at the branch head; they run in the Android companion CI job's `:app:testDebugUnitTest`)

| # | Test (proposed file) | Proves |
| --- | --- | --- |
| 1 | `failedTurnKeepsItsErrorBubbleAndClearsOnlyThePartialAndHomePreview` (`LocalReplyTurnTest.kt`); the existing tests, renamed `failedStreamDropsThePartialAndKeepsTheErrorBubble` and `idleStallRaisesTypedErrorAndStopsDecode`, assert `prior` plus exactly one error bubble instead of `messages == prior` | D: the CoS ruling |
| 2 | `failedTurnErrorBubbleIsNeverSavedOrQueued` (`CompanionModelOffgridTurnTest.kt`, fake engine and pack manager, through `sendOffgrid`) | D: bubble absent from the local store and the offline queue |
| 3 | `stallThroughSendOffgridReleasesTheRealSendLock` (same file; `loadDeadlineThroughSendOffgridRaisesTheTypedErrorAndReleasesTheLock` and `overallTurnCapThroughSendOffgridRaisesTheTypedErrorAndReleasesTheRealSendLock` drive the load and turn-cap stalls through it too) | A: `CompanionModel.sendLock`, not a test-local mutex |
| 4 | `sendOffgridLandsTheReplyAndClearsTheHomePreview` (same file) | D: the `sendOffline` wiring of `answer`, `landed`, `onFinally` |
| 5 | `defaultStallDeadlinesAre120s30s180sAnd300s` (the default-values test, now covering all four) and `nonPositiveStallDeadlineIsRejected` (`LocalReplyTurnTest.kt`) | A: the defaults |
| 6 | `sectionSummaryPassStallRaisesTypedError` (`LocalReplyTurnTest.kt`) | A: summary passes are watched |
| 7 | `stalledTurnUnloadsTheEngineAndLeavesPackReadyWithNoPackError` (`LocalReplyTurnTest.kt`) | A, C |
| 8 | `cancelledTurnUnloadsTheEngineAndClearsPicked` and `keepWarmKeepsTheModelOnlyAfterASuccessfulTurn` (`LocalReplyTurnTest.kt`) | C |
| 9 | `phoneToolPassesShowTheMemoryPressureWarning` (`CompanionModelOffgridTurnTest.kt`) | B: the phone-tool path |
| 10 | `desktopPollDuringALocalAnswerLeavesActivityAndMessagesAlone` (`CompanionModelOffgridTurnTest.kt`) | B |
| 11 | `homeShowsTheStreamedReplyOnce` (`HomeLiveReplyUiTest.kt`, Compose, the Home block extracted into an `internal` composable) | E |
| 12 | `installFastPhoneModelPublishesTheHomeStatusLines` (`CompanionModelDownloadTest.kt`, fake pack manager) | E: "Downloading fast phone model · N%" and "Fast phone model ready" |
| 13 | `memorySpeedFastModelSectionShowsTransferAndReadyLine` (`PhoneMemoryUiTest.kt`) | E |
| 14 | `failedDownloadSetsErrorAndRetryClearsIt`, `fastModelButtonIsDisabledWhileItsDownloadRuns` (`CompanionModelDownloadTest.kt`) | F |
| 15 | `selectCompanionPackLeavesErrorAndBusyUntouched` (`CompanionModelDownloadTest.kt`) | F |
| 16 | `libraryCardShowsNoSecondBarForTheSelectedPackWhileTheLegacyBarIsVisible` (`ModelScreensLiveUiTest.kt`; `modelsCardKeepsLegacyPercentDuringATrackedDownload` no longer asserts two bars) | F |
| 17 | `downloadedContentShowsModelTransferRows` (`DownloadedContentUiTest.kt`) | F |
| 18 | `loadPhaseDeadlineIs180sAndRaisesTypedError` (`LocalReplyTurnTest.kt`, fake engine whose load never becomes ready, injected clock) | A: load phase, `deadline = load` |
| 19 | `overallTurnCapIs300sAcrossSummaryPasses` (`LocalReplyTurnTest.kt`, several summary passes each under their own first-token and idle budgets whose sum passes 300 s) | A: turn cap, `deadline = turn` |
| 20 | `loadAndTurnCapStallsFailTheTurnLikeAnyOtherStall` (`LocalReplyTurnTest.kt`: error bubble, lock, cleanup; the real `sendLock` is covered by row 3, which drives the load and turn-cap stalls too) | A, D: one failure path (added by the Architect to cover the same-path criterion) |

### Live-UI add-alongside reasoning

| Existing live element | What this RFC does to it | Why it is add-alongside |
| --- | --- | --- |
| Home status line (`activity`) | adds the stage ticker text and the fast-model lines | the same field with more text; a desktop poll does not overwrite it while a local answer runs |
| Home last-assistant line | stays; not rendered only while the streamed preview shows the same text | it is hidden only as a duplicate of the new streamed line (criterion E) and renders as before when no preview is active |
| Home streamed line (`liveLocalReply`) | new | added below the existing lines; cleared when the turn ends |
| Chat error bubble of a failed turn | **kept** (CoS ruling); only the partial is removed | removing it would have deleted live behaviour; the bubble is unsaved as before |
| Models screen status line, pack dropdown, Download / Re-download, Delete, Load from file, the legacy bar and "Downloading… N%", and every other existing message there | unchanged; the transfer view is layered on top and skips its own bar while the legacy bar shows | every control and message keeps its place and condition |
| "All models" library cards, Downloaded content transfer rows, Memory & speed transfer view and ready line | new | pure additions beside the existing cards |
| Setup card (Download model, Load from file) | unchanged controls; transfer view added | same as the Models screen |
| `PhoneSetupCard`, `CompanionModelsSection` | visibility `private` to `internal` for tests | no behaviour change |

**Astra boundary:** persona, WebGL, presence, solar, orb and HUD components are not touched, and no context-usage plumbing is added (that stays in RFC-0234, #650).

### Gaps against this text: closed at the #671 branch head, except the turn-cap start (verified by UX; each checked against the code)

*Pinned by CoS, 2026-11-03:* the 180 s load deadline and the 300 s overall turn cap (formerly item 6 of this list: no deadline on model load and no overall limit) are a requirement on #671 itself, not a disclosed gap. The load deadline is met (criterion A). The turn cap is **open** (item 7).

1. **Closed.** `LocalReplyTurn.failed` ends with `prior` plus the unsaved error bubble; only `discard` (cancellation) sets `messages = prior`. Tests: `failedTurnKeepsItsErrorBubbleAndClearsOnlyThePartialAndHomePreview`, `failedStreamDropsThePartialAndKeepsTheErrorBubble`, `idleStallRaisesTypedErrorAndStopsDecode`.
2. **Closed.** Home (`MainActivity`, the Home reply lines) renders the last-assistant line only while `liveLocalReply` is blank. Test: `HomeLiveReplyUiTest.homeShowsTheStreamedReplyOnce`.
3. **Closed.** `CompanionModel.downloadModelPack` sets `error = null` and `busy` on start, sets `error` on a non-cancel failure, and keeps `busy` until the last active download ends. Tests: `CompanionModelDownloadTest.failedDownloadSetsErrorAndRetryClearsIt`, `fastModelButtonIsDisabledWhileItsDownloadRuns`.
4. **Closed.** `ModelLibraryCards` takes a `showBar` predicate and the Models screen passes `showBar = { it.id != devicePack.selectedPackId }`, so the selected pack's library card draws no second bar. Test: `ModelScreensLiveUiTest.libraryCardShowsNoSecondBarForTheSelectedPackWhileTheLegacyBarIsVisible`.
5. **Closed.** `phoneLocalAnswer` reads the pressure reason and reports it through `turn::pressure`, and `LocalReplyTurn.pressure` writes `activity` only while the turn is open. Tests: `CompanionModelOffgridTurnTest.phoneToolPassesShowTheMemoryPressureWarning`, `stageTickerKeepsTheMemoryPressureWarningVisible`.
6. **Closed.** `CompanionPackManager.downloadSelected()` is removed; every download goes through `downloadModelPack`.
7. **Open: the 300 s cap must start when the turn starts and cover the whole turn (CoS ruling; the spec stands, the code follows).** `CompanionPackManager.TurnGuard` starts its clock per `CompanionPackManager.generate` call. One call's load, summary passes and reply pass share the cap, but the time before that call is not counted, and each `generate` of the phone-tool loop in `phoneLocalAnswer` gets its own 300 s. The PR fixer is moving the cap's start to `LocalReplyTurn`'s opening; criterion A's turn-cap line stays unmet until then.

## Files

All under `android/app/src/main/java/com/jarvis/companion/` unless noted: CompanionModel (turn wiring, `installFastPhoneModel`, `downloadModelPack`, `selectCompanionPack`), CompanionPackManager (`watchedGenerate`, downloads, `packFileSnapshot`), **LocalReplyTurn** (new: stage ticker, preview, cleanup wiring, landed and failed turns), **LocalStreamStall** (new: `LocalStallDeadlines`, `LocalStreamStallError`), LiveLocalReply, LocalInferenceEngine, `android/app/src/main/cpp/jarvis_llama.cpp`, MainActivity (Home live-reply line and the Models section), ModelDownloadState, ModelDownloadsUi, CompanionDeviceModelChrome, DevicePackChromePublisher, PhoneMemoryUi and DownloadedContentUi. `GenerateOutcome.kt::withOfflineAnswerCleanup` is used unchanged.

Tests, under `android/app/src/test/java/com/jarvis/companion/`: LiveLocalReplyTest, **LocalReplyTurnTest** (new), ModelDownloadFeedbackTest, ModelDownloadsUiTest, ModelScreensLiveUiTest and PackFileSnapshotTest; existing StandaloneModeTest is cited for cleanup. Added for the spec: CompanionModelOffgridTurnTest (with the CompanionModelHarness helper), CompanionModelDownloadTest, HomeLiveReplyUiTest, PhoneMemoryUiTest and DownloadedContentUiTest (see *Tests the spec added*).

## Out of scope

- The solar HUD and context-usage display (RFC-0234 HUD part, #650).
- Desktop inference, voice synthesis redesign, and changing phone tool permissions.

## Validation

See the PR. Physical-phone first-token timings, warm-cache speedup and installation remain unverified; no phone is attached.
