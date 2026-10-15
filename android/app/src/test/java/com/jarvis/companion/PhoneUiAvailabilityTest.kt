package com.jarvis.companion

import org.junit.Assert.*
import org.junit.Test

class PhoneUiAvailabilityTest {
    @Test fun firstRunOnlyOffersWorkingLocalDestinations() {
        assertEquals(listOf("Home", "Chat", "More"), PhoneUiAvailability.tabs(false, false))
        assertFalse(PhoneUiAvailability.tabs(true, true).contains("Studio"))
    }
    @Test fun newerSecondaryScreensAndOptionalPylonRemainReachable() {
        val tabs = PhoneUiAvailability.tabs(true, true, true)
        assertTrue(tabs.contains("Offgrid"))
        assertTrue(tabs.size <= 5)
        for (screen in listOf("Memory", "Assistant", "Offgrid", "Offgrid chat", "Notifications"))
            assertTrue(screen, PhoneUiAvailability.destinationAvailable(screen, tabs))
        assertFalse(PhoneUiAvailability.destinationAvailable("Studio", tabs))
    }
    @Test fun cachedTasksRemainReadableButOfflineMutationsAreDisabled() {
        assertTrue(PhoneUiAvailability.tabs(false, true).contains("Tasks"))
        assertFalse(PhoneUiAvailability.desktopActionsEnabled(false, false))
        assertFalse(PhoneUiAvailability.desktopActionsEnabled(true, true))
        assertTrue(PhoneUiAvailability.desktopActionsEnabled(true, false))
    }
    @Test fun manualPairingRequiresOriginFingerprintAndCompleteCode() {
        val pin = "a".repeat(64)
        assertTrue(PhoneUiAvailability.manualPairingReady("https://192.168.1.2:4781", pin, "123456"))
        assertFalse(PhoneUiAvailability.manualPairingReady("", pin, "123456"))
        assertFalse(PhoneUiAvailability.manualPairingReady("http://192.168.1.2:4781", pin, "123456"))
        assertFalse(PhoneUiAvailability.manualPairingReady("https://192.168.1.2:4781", "", "123456"))
        assertFalse(PhoneUiAvailability.manualPairingReady("https://192.168.1.2:4781", pin, "123"))
        assertTrue(PhoneUiAvailability.manualPairingReady("https://192.168.1.2:4781", pin, "", paired = true))
        assertFalse(PhoneUiAvailability.manualPairingReady("http://192.168.1.2:4781", pin, "", paired = true))
    }
}
