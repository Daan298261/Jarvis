package com.jarvis.companion

/**
 * Deadlines for one native generation pass, mirroring the desktop provider stall contract
 * (`StreamStallError`, first_token and idle). [firstTokenMs] runs from the start of the pass
 * (prefill included) to the first token; [idleMs] is the longest gap between two tokens.
 */
data class LocalStallDeadlines(
    val firstTokenMs: Long = 120_000,
    val idleMs: Long = 30_000,
    val clockMs: () -> Long = { System.nanoTime() / 1_000_000 },
) {
    init { require(firstTokenMs > 0 && idleMs > 0) { "Stall deadlines must be positive" } }
    /** Watchdog poll interval: fine enough to fire within a quarter of the shorter deadline. */
    val checkEveryMs: Long get() = (minOf(firstTokenMs, idleMs) / 4).coerceIn(10, 1_000)
}

/**
 * Typed outcome when an on-device pass exceeds a stall deadline. Native decode has already been
 * asked to stop; the turn fails with this message (shown as an error) and releases the send lock.
 */
class LocalStreamStallError(
    val deadline: String,
    val elapsedMs: Long,
    val budgetMs: Long,
    val model: String,
) : IllegalStateException(
    "On-device reply stalled ($deadline): ${elapsedMs / 1000}s without ${if (deadline == FIRST_TOKEN) "a first token" else "a new token"}, " +
        "limit ${budgetMs / 1000}s on $model. The model was stopped; try again or choose a smaller model.",
) {
    companion object {
        const val FIRST_TOKEN = "first_token"
        const val IDLE = "idle"
    }
}
