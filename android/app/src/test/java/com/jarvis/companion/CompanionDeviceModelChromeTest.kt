package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionDeviceModelChromeTest {
    @Test
    fun offlineBannerHiddenWhenConnected() {
        assertNull(offlineChatBanner(leaderConnected = true, paired = true, packStatus = DevicePackStatus.READY))
    }

    @Test
    fun offlineBannerShowsOnDeviceWhenPackReady() {
        assertEquals(
            "ANZU desktop unreachable — answering on this phone. Chats sync when the desktop is back.",
            offlineChatBanner(leaderConnected = false, paired = true, packStatus = DevicePackStatus.READY),
        )
    }

    @Test
    fun unpairedPhoneStillGetsOfflineGuidance() {
        val ready = offlineChatBanner(leaderConnected = false, paired = false, packStatus = DevicePackStatus.READY)!!
        assertTrue(ready.contains("on this phone"))
        val missing = offlineChatBanner(leaderConnected = false, paired = false, packStatus = DevicePackStatus.MISSING)!!
        assertTrue(missing.contains("More → Models"))
        assertFalse(missing.contains("Leader"))
    }
}
