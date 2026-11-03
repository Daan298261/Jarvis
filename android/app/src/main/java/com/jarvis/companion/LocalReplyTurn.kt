package com.jarvis.companion

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicReference

/**
 * UI state of one on-device reply turn (RFC-0235): the stage line on Home, the streamed preview on
 * Home and in Chat, and what is left behind when the turn ends.
 *
 * - The stage ticker never hides a memory-pressure warning: once [pressure] is set, every tick
 *   starts with that warning.
 * - A turn that does not land a saved reply (cancelled, failed or stalled) leaves no partial
 *   assistant bubble in Chat and no preview on Home. A failure is shown through `error` and, as it
 *   always was, keeps its unsaved error bubble in Chat (live UI is add-only); a cancel leaves neither.
 * - A landed reply lives in `messages`; the streamed Home preview is cleared.
 */
internal class LocalReplyTurn(
    private val state: MutableStateFlow<CompanionState>,
    private val prior: List<JSONObject>,
    private val assistantId: String,
    private val clockMs: () -> Long = android.os.SystemClock::elapsedRealtime,
) {
    private val started = clockMs()
    private val stage = AtomicReference("Preparing answer")
    private val pressure = AtomicReference<String?>(null)
    @Volatile private var open = true

    /** Coalesced token sink; publishes the partial reply to Home and as the pending Chat bubble. */
    val reply = LiveLocalReply(clockMs) { partial ->
        if (open) state.update {
            it.copy(liveLocalReply = partial, messages = prior +
                StandaloneActions.chatMessage(assistantId, "assistant", partial, StandaloneActions.ORIGIN_ASSISTANT))
        }
    }

    val progress: (String) -> Unit = { stage.set(it) }

    /** Remembers the warning for every later tick; writes it now only while the turn is open. */
    fun pressure(reason: String) {
        pressure.set(reason)
        if (open) state.update { it.copy(activity = reason) }
    }

    fun activityLine(): String =
        listOfNotNull(pressure.get(), stage.get(), "${(clockMs() - started) / 1000}s").joinToString(" · ")

    fun tick() {
        if (open) state.update { it.copy(activity = activityLine()) }
    }

    fun ticker(scope: CoroutineScope): Job = scope.launch {
        while (isActive) {
            tick()
            delay(1000)
        }
    }

    /**
     * Runs the turn's [block] under [withOfflineAnswerCleanup] with the stage ticker in [scope].
     * A cancelled turn rethrows after dropping its partial reply; a failed or stalled turn returns
     * the failure after showing it as an error (and its error bubble).
     */
    suspend fun <T> answer(
        scope: CoroutineScope,
        packManager: CompanionPackManager,
        clearPicked: () -> Unit,
        keepWarm: () -> Boolean,
        onStart: () -> Unit,
        onFinally: () -> Unit,
        block: suspend () -> T,
    ): Result<T> {
        var answered = false
        var ticker: Job? = null
        return withOfflineAnswerCleanup(
            packManager = packManager,
            clearPicked = clearPicked,
            keepWarm = keepWarm,
            onStart = { onStart(); ticker = ticker(scope) },
            onFinally = {
                ticker?.cancel()
                if (!answered) discard()
                onFinally()
            },
        ) { block().also { answered = true } }
            .onFailure { failed(it.message ?: "On-device answer failed") }
    }

    /** Cancelled, failed or stalled: drop the unsaved partial reply from Chat and Home. */
    fun discard() {
        open = false
        state.update { it.copy(liveLocalReply = "", messages = prior) }
    }

    /**
     * The turn failed: only the partial reply and the Home preview are dropped. The error stays
     * visible as `error` and keeps its unsaved error bubble in Chat, exactly as before this change;
     * it is never persisted or queued as a reply.
     */
    fun failed(message: String) {
        open = false
        state.update {
            it.copy(
                liveLocalReply = "",
                messages = prior + StandaloneActions.chatMessage(assistantId, "assistant", message, StandaloneActions.ORIGIN_ASSISTANT),
                error = message,
            )
        }
    }

    /** The reply is saved and shown in Chat; Home's streamed preview is no longer needed. */
    fun landed(assistantMessage: JSONObject) {
        open = false
        state.update { it.copy(liveLocalReply = "", messages = prior + assistantMessage) }
    }
}
