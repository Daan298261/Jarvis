package com.jarvis.companion

import kotlinx.coroutines.delay
import kotlin.random.Random

/**
 * Retry with full jitter for the pairing/session handshake (pairing-stability fix 7).
 * The pinned client deliberately disables OkHttp's silent retry; a Wi-Fi hand-off or
 * a desktop that is still starting used to fail pairing on the first dropped
 * connection. Only transport errors (IOException) retry — server answers such as an
 * expired code (ApiException) surface immediately. Enroll, LAN enroll, challenge and
 * session are idempotent per device key on the desktop, so repeating them is safe.
 */
object TransientRetry {
    const val DEFAULT_ATTEMPTS = 3
    const val BASE_DELAY_MS = 400L
    const val MAX_DELAY_MS = 4_000L

    /** Full-jitter delay before retry [attempt] (1-based): uniform in [0, min(cap, base * 2^(attempt-1))]. */
    fun delayMs(
        attempt: Int,
        random: Random = Random.Default,
        baseDelayMs: Long = BASE_DELAY_MS,
        maxDelayMs: Long = MAX_DELAY_MS,
    ): Long {
        val ceiling = (baseDelayMs shl (attempt - 1).coerceIn(0, 10)).coerceAtMost(maxDelayMs)
        return random.nextLong(ceiling + 1)
    }

    suspend fun <T> run(
        attempts: Int = DEFAULT_ATTEMPTS,
        random: Random = Random.Default,
        baseDelayMs: Long = BASE_DELAY_MS,
        maxDelayMs: Long = MAX_DELAY_MS,
        sleep: suspend (Long) -> Unit = { delay(it) },
        onRetry: (attempt: Int, error: java.io.IOException) -> Unit = { _, _ -> },
        block: suspend () -> T,
    ): T {
        var last: java.io.IOException? = null
        for (attempt in 1..attempts.coerceAtLeast(1)) {
            try {
                return block()
            } catch (error: java.io.IOException) {
                last = error
                if (attempt < attempts) {
                    onRetry(attempt, error)
                    sleep(delayMs(attempt, random, baseDelayMs, maxDelayMs))
                }
            }
        }
        throw last ?: java.io.IOException("No reachable ANZU endpoint")
    }
}
