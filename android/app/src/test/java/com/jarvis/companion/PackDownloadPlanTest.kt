package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PackDownloadPlanTest {
    private val size = 1_270_807_936L

    @Test
    fun resumesFromPartialAndRestartsWhenOversized() {
        assertEquals(0L, PackDownloadPlan.resumeFrom(0L, size))
        assertEquals(500L, PackDownloadPlan.resumeFrom(500L, size))
        assertEquals(0L, PackDownloadPlan.resumeFrom(size + 1, size))
        assertTrue(PackDownloadPlan.partialIsComplete(size, size))
        assertFalse(PackDownloadPlan.partialIsComplete(size - 1, size))
    }

    @Test
    fun appendsOnlyWhenServerHonoursRange() {
        assertTrue(PackDownloadPlan.appendToPartial(500L, 206))
        assertFalse(PackDownloadPlan.appendToPartial(500L, 200))
        assertFalse(PackDownloadPlan.appendToPartial(0L, 206))
    }

    @Test
    fun storagePrecheckCountsOnlyRemainingBytesPlusMargin() {
        val half = size / 2
        assertEquals(size - half + PackDownloadPlan.STORAGE_MARGIN_BYTES, PackDownloadPlan.requiredFreeBytes(size, half))
        assertNull(PackDownloadPlan.storageBlockReason(size + PackDownloadPlan.STORAGE_MARGIN_BYTES, size, 0L))
        val reason = PackDownloadPlan.storageBlockReason(100L * 1024 * 1024, size, 0L)
        assertTrue(reason!!.contains("Not enough storage"))
        assertNull(PackDownloadPlan.storageBlockReason(PackDownloadPlan.STORAGE_MARGIN_BYTES, size, size))
    }
}
