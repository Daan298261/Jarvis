package com.jarvis.companion

/**
 * Deadlines for one on-device reply, mirroring the desktop provider stall contract
 * (`StreamStallError`, first_token and idle) and adding two bounds the phone needs.
 * - [firstTokenMs] runs from the start of a native pass (prefill included) to its first token.
 * - [idleMs] is the longest gap between two tokens of a pass.
 * - [loadMs] bounds loading the model into memory (180 s).
 * - [turnMs] caps one whole [CompanionPackManager.generate] call (300 s): the load, every section
 *   summary pass of a sectioned prompt, and the reply pass together.
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
