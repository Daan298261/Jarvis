package com.jarvis.companion.device

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DeviceModelTypesTest {
    @Test
    fun useOnDeviceInferenceOnlyWhenLeaderDownAndPackReady() {
        assertEquals(false, useOnDeviceInference(true, DevicePackStatus.READY))
        assertEquals(false, useOnDeviceInference(false, DevicePackStatus.MISSING))
        assertEquals(true, useOnDeviceInference(false, DevicePackStatus.READY))
        assertEquals(true, useOnDeviceInference(false, DevicePackStatus.RUNNING))
    }

    @Test
    fun offlineBannerHiddenWhenConnectedOrUnpaired() {
        assertNull(offlineChatBanner(leaderConnected = true, paired = true, packStatus = DevicePackStatus.READY))
        assertNull(offlineChatBanner(leaderConnected = false, paired = false, packStatus = DevicePackStatus.READY))
    }

    @Test
    fun offlineBannerShowsOnDeviceMessageWhenPackReady() {
        assertEquals(
            "Leader unreachable — answering on-device.",
            offlineChatBanner(leaderConnected = false, paired = true, packStatus = DevicePackStatus.READY),
        )
    }
}
