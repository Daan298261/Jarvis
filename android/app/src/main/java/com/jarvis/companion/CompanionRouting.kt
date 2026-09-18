package com.jarvis.companion

/** RFC-0108 online/offline routing — Leader orchestrates when reachable. */
enum class RoutingMode {
    LEADER_ORCHESTRATED,
    DEVICE_OFFLINE,
    DEVICE_BLOCKED,
}

data class RoutingDecision(
    val mode: RoutingMode,
    val reason: String = "",
)

object CompanionRouting {
    fun decide(
        leaderReachable: Boolean,
        packStatus: String,
        resourceBlocked: String?,
        hasStalePendingOnlineOutbox: Boolean,
    ): RoutingDecision {
        if (leaderReachable) {
            return RoutingDecision(RoutingMode.LEADER_ORCHESTRATED)
        }
        if (hasStalePendingOnlineOutbox) {
            return RoutingDecision(
                RoutingMode.DEVICE_BLOCKED,
                "Resolve the pending online message before chatting offline",
            )
        }
        resourceBlocked?.let {
            return RoutingDecision(RoutingMode.DEVICE_BLOCKED, it)
        }
        return when (packStatus) {
            CompanionPackStatus.READY, CompanionPackStatus.RUNNING -> RoutingDecision(RoutingMode.DEVICE_OFFLINE)
            CompanionPackStatus.MISSING -> RoutingDecision(
                RoutingMode.DEVICE_BLOCKED,
                "Install a companion model pack in More → Models to chat while Jarvis is offline",
            )
            CompanionPackStatus.DOWNLOADING -> RoutingDecision(
                RoutingMode.DEVICE_BLOCKED,
                "Model pack is still downloading",
            )
            CompanionPackStatus.ERROR -> RoutingDecision(
                RoutingMode.DEVICE_BLOCKED,
                "Companion model failed — retry download or free storage",
            )
            else -> RoutingDecision(
                RoutingMode.DEVICE_BLOCKED,
                "Companion model is not ready ($packStatus)",
            )
        }
    }

    fun shouldSyncAfterLeaderReturn(wasOffline: Boolean, leaderReachable: Boolean, queuedTurns: Int): Boolean =
        wasOffline && leaderReachable && queuedTurns > 0
}
