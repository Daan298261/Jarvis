package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Test

class CompanionRoutingTest {
    @Test
    fun leaderReachableUsesOrchestrator() {
        val decision = CompanionRouting.decide(
            leaderReachable = true,
            packStatus = "missing",
            resourceBlocked = null,
            hasStalePendingOnlineOutbox = false,
        )
        assertEquals(RoutingMode.LEADER_ORCHESTRATED, decision.mode)
    }

    @Test
    fun offlineRequiresReadyPack() {
        val blocked = CompanionRouting.decide(
            leaderReachable = false,
            packStatus = "missing",
            resourceBlocked = null,
            hasStalePendingOnlineOutbox = false,
        )
        assertEquals(RoutingMode.DEVICE_BLOCKED, blocked.mode)

        val offline = CompanionRouting.decide(
            leaderReachable = false,
            packStatus = "ready",
            resourceBlocked = null,
            hasStalePendingOnlineOutbox = false,
        )
        assertEquals(RoutingMode.DEVICE_OFFLINE, offline.mode)
    }

    @Test
    fun pendingOnlineOutboxBlocksOffline() {
        val decision = CompanionRouting.decide(
            leaderReachable = false,
            packStatus = "ready",
            resourceBlocked = null,
            hasStalePendingOnlineOutbox = true,
        )
        assertEquals(RoutingMode.DEVICE_BLOCKED, decision.mode)
    }
}
