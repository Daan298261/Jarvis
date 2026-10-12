package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LeaderHeartbeatTest {
    @Test
    fun singleDropDoesNotFlipOfflineAndIsRecheckedQuickly() {
        val beat = LeaderHeartbeat()
        assertEquals(LeaderHeartbeat.CONNECTED_POLL_MS, beat.nextDelayMs())
        assertFalse(beat.onFailure())
        assertEquals(LeaderHeartbeat.CONFIRM_POLL_MS, beat.nextDelayMs())
        assertTrue(beat.onFailure())
    }

    @Test
    fun unreachableDesktopBacksOffToCap() {
        val beat = LeaderHeartbeat()
        val delays = (1..8).map { beat.onFailure(); beat.nextDelayMs() }
        assertEquals(listOf(1_500L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L, 30_000L, 30_000L), delays)
    }

    @Test
    fun networkChangeAndSuccessResetBackoff() {
        val beat = LeaderHeartbeat()
        repeat(5) { beat.onFailure() }
        beat.onNetworkChanged()
        assertEquals(LeaderHeartbeat.CONFIRM_POLL_MS, beat.nextDelayMs())
        beat.onSuccess()
        assertEquals(LeaderHeartbeat.CONNECTED_POLL_MS, beat.nextDelayMs())
        beat.onNetworkChanged()
        assertEquals(LeaderHeartbeat.CONNECTED_POLL_MS, beat.nextDelayMs())
    }
}
