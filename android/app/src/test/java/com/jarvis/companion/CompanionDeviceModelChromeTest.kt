package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CompanionDeviceModelChromeTest {
    @Test
    fun offlineBannerHiddenWhenConnectedOrUnpaired() {
        assertNull(offlineChatBanner(leaderConnected = true, paired = true, packStatus = DevicePackStatus.READY))
        assertNull(offlineChatBanner(leaderConnected = false, paired = false, packStatus = DevicePackStatus.READY))
    }

    @Test
    fun offlineBannerShowsOnDeviceWhenPackReady() {
        assertEquals(
            "Leader unreachable — answering on-device.",
            offlineChatBanner(leaderConnected = false, paired = true, packStatus = DevicePackStatus.READY),
        )
    }
}
