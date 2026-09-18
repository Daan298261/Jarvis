package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Test

class DevicePackChromePublisherTest {
    @Test
    fun mapsPackStatusesForUxChrome() {
        assertEquals(DevicePackStatus.MISSING, DevicePackChromePublisher.toDeviceStatus(CompanionPackStatus.MISSING))
        assertEquals(DevicePackStatus.DOWNLOADING, DevicePackChromePublisher.toDeviceStatus(CompanionPackStatus.DOWNLOADING))
        assertEquals(DevicePackStatus.READY, DevicePackChromePublisher.toDeviceStatus(CompanionPackStatus.READY))
        assertEquals(DevicePackStatus.RUNNING, DevicePackChromePublisher.toDeviceStatus(CompanionPackStatus.RUNNING))
        assertEquals(DevicePackStatus.ERROR, DevicePackChromePublisher.toDeviceStatus(CompanionPackStatus.ERROR))
        assertEquals(DevicePackStatus.MISSING, DevicePackChromePublisher.toDeviceStatus("unknown"))
    }
}
