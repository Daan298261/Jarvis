package com.jarvis.companion

/**
 * Desktop reachability heartbeat (pairing-stability fix 8).
 *
 * The companion polls the desktop every few seconds. One dropped poll used to flip the
 * app to "Offline" (flapping on a Wi-Fi hiccup), and a down desktop was then hammered
 * at the same rate. Now two consecutive failures are needed before going offline, a
 * single failure is re-checked quickly, an unreachable desktop is polled with backoff
 * up to 30 s, and a network change resets the backoff so reconnection is immediate.
 */
class LeaderHeartbeat(private val failuresBeforeOffline: Int = 2) {
    var consecutiveFailures: Int = 0
        private set

    fun onSuccess() {
        consecutiveFailures = 0
    }

    /** Records a failed poll; returns true once the desktop should be shown as unreachable. */
    fun onFailure(): Boolean {
        consecutiveFailures++
        return consecutiveFailures >= failuresBeforeOffline
    }

    /** Wi-Fi/cellular changed: the old failures say nothing about the new network. */
    fun onNetworkChanged() {
        if (consecutiveFailures > 0) consecutiveFailures = 1
    }

    fun nextDelayMs(): Long = when (consecutiveFailures) {
        0 -> CONNECTED_POLL_MS
        1 -> CONFIRM_POLL_MS
        else -> (CONNECTED_POLL_MS shl (consecutiveFailures - 2).coerceAtMost(4)).coerceAtMost(MAX_POLL_MS)
    }

    companion object {
        const val CONNECTED_POLL_MS = 4_000L
        const val CONFIRM_POLL_MS = 1_500L
        const val MAX_POLL_MS = 30_000L
    }
}
