package com.jarvis.companion

import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Deadlines for one on-device reply, mirroring the desktop provider stall contract
 * (`StreamStallError`, first_token and idle) and adding two bounds the phone needs.
 * - [firstTokenMs] runs from the start of a native pass (prefill included) to its first token.
 * - [idleMs] is the longest gap between two tokens of a pass.
 * - [loadMs] bounds loading the model into memory (180 s).
 * - [turnMs] caps one whole turn (300 s), measured from the moment the turn opens ([LocalTurnBudget]):
 *   every [CompanionPackManager.generate] call of the turn together, i.e. each load, every section
 *   summary pass of a sectioned prompt, the reply pass and every phone-tool step. It never restarts
 *   per call or per pass.
 */
data class LocalStallDeadlines(
    val firstTokenMs: Long = 120_000,
    val idleMs: Long = 30_000,
    val loadMs: Long = 180_000,
    val turnMs: Long = 300_000,
    val clockMs: () -> Long = { System.nanoTime() / 1_000_000 },
) {
    init { require(firstTokenMs > 0 && idleMs > 0 && loadMs > 0 && turnMs > 0) { "Stall deadlines must be positive" } }
    /** Watchdog poll interval: fine enough to fire within a quarter of the shortest deadline. */
    val checkEveryMs: Long get() = (minOf(firstTokenMs, idleMs, loadMs, turnMs) / 4).coerceIn(10, 1_000)
}

/**
 * Typed outcome when an on-device pass exceeds a deadline. Native decode has already been asked to
 * stop; the turn fails with this message (shown as an error) and releases the send lock.
 * [deadline] is [FIRST_TOKEN], [IDLE], [LOAD] or [TURN].
 */
class LocalStreamStallError(
    val deadline: String,
    val elapsedMs: Long,
    val budgetMs: Long,
    val model: String,
) : IllegalStateException(
    "On-device reply stalled ($deadline): " + when (deadline) {
        FIRST_TOKEN -> "${elapsedMs / 1000}s without a first token"
        IDLE -> "${elapsedMs / 1000}s without a new token"
        LOAD -> "loading the model took ${elapsedMs / 1000}s"
        else -> "the reply took ${elapsedMs / 1000}s in total"
    } + ", limit ${budgetMs / 1000}s on $model. The model was stopped; try again or choose a smaller model.",
) {
    companion object {
        const val FIRST_TOKEN = "first_token"
        const val IDLE = "idle"
        const val LOAD = "load"
        const val TURN = "turn"
    }
}

/**
 * The one time budget and cancel scope of an on-device reply turn (RFC-0235). It is opened once, when
 * the turn opens ([CompanionPackManager.openTurn]), and passed to every [CompanionPackManager.generate]
 * call of that turn: the chat reply, each section summary and every phone-tool step. So:
 * - the [LocalStallDeadlines.turnMs] cap runs from [startedAtMs] across all of them and never restarts;
 * - a cancel is remembered for the rest of the turn, so a stop that lands between two passes stops the
 *   next pass before it starts instead of being lost. [engineTurn] is the engine's own turn token
 *   ([LocalInferenceEngine.beginTurn]), which makes native decode refuse a pass after such a cancel too.
 */
class LocalTurnBudget internal constructor(
    private val deadlines: LocalStallDeadlines,
    internal val engineTurn: Long,
) {
    val startedAtMs: Long = deadlines.clockMs()
    private val cancelled = AtomicBoolean(false)
    private val capped = AtomicReference<LocalStreamStallError?>(null)

    private val cancelSignal = kotlinx.coroutines.CompletableDeferred<Unit>()

    /** The model the turn last ran on; named in a cap error raised outside a pass (a phone-action approval wait). */
    @Volatile internal var model: String = ""

    val isCancelled: Boolean get() = cancelled.get()

    internal fun cancel() {
        cancelled.set(true)
        cancelSignal.complete(Unit)
    }

    /** Suspends until the turn is cancelled; resumes at once when [cancel] runs (no polling). */
    suspend fun awaitCancel() = cancelSignal.await()

    /** Milliseconds left of the turn's [LocalStallDeadlines.turnMs] cap (0 once it has passed). */
    fun remainingMs(): Long = (deadlines.turnMs - (deadlines.clockMs() - startedAtMs)).coerceAtLeast(0)

    /** The typed turn-cap error once the cap has passed, else null. */
    fun capError(): LocalStreamStallError? = overCap(model)

    /** The turn-cap error once [LocalStallDeadlines.turnMs] has passed since [startedAtMs]; the first one is kept. */
    internal fun overCap(model: String): LocalStreamStallError? {
        capped.get()?.let { return it }
        val elapsed = deadlines.clockMs() - startedAtMs
        if (elapsed <= deadlines.turnMs) return null
        capped.compareAndSet(null, LocalStreamStallError(LocalStreamStallError.TURN, elapsed, deadlines.turnMs, model))
        return capped.get()
    }
}
