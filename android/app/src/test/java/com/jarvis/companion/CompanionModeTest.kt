package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionModeTest {
    @Test
    fun desktopWinsWhenConnected() {
        assertEquals(AnswerMode.DESKTOP, CompanionMode.answerMode(connected = true, pendingApproval = false, localModelReady = true))
        assertEquals("● DESKTOP", CompanionMode.indicator(true, false, false, paired = true).label)
    }

    @Test
    fun phoneAnswersWhenModelReadyAndNoDesktop() {
        val unpaired = CompanionMode.indicator(connected = false, pendingApproval = false, localModelReady = true, paired = false)
        assertEquals(AnswerMode.PHONE, unpaired.mode)
        assertEquals("◐ ON THIS PHONE", unpaired.label)
        assertTrue(unpaired.detail.contains("Nothing leaves the device"))
        val paired = CompanionMode.indicator(connected = false, pendingApproval = false, localModelReady = true, paired = true)
        assertTrue(paired.detail.contains("syncs"))
    }

    @Test
    fun pendingApprovalDoesNotHideAReadyPhoneModel() {
        assertEquals(AnswerMode.PHONE, CompanionMode.answerMode(connected = false, pendingApproval = true, localModelReady = true))
        assertEquals(AnswerMode.WAITING_APPROVAL, CompanionMode.answerMode(connected = false, pendingApproval = true, localModelReady = false))
    }

    @Test
    fun setupNeededOnlyWithoutDesktopOrModel() {
        assertTrue(CompanionMode.needsPhoneSetup(connected = false, localModelReady = false))
        assertFalse(CompanionMode.needsPhoneSetup(connected = false, localModelReady = true))
        assertFalse(CompanionMode.needsPhoneSetup(connected = true, localModelReady = false))
    }

    @Test
    fun everyDesktopFeatureExplainsItselfWithoutInternals() {
        DesktopFeature.values().forEach { feature ->
            val copy = CompanionMode.desktopOnlyNotice(feature)
            assertTrue(feature.name, copy.isNotBlank())
            assertFalse(feature.name, copy.contains("Leader"))
            assertFalse(feature.name, Regex("""\bJarvis\b""").containsMatchIn(copy))
        }
    }
}
