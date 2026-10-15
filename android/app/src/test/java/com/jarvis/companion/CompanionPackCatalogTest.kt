package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionPackCatalogTest {
    @Test
    fun builtInRecommendedPackIsPinnedLowMemoryDefault() {
        val pack = CompanionPackCatalog.builtIn.first { it.recommended }
        assertEquals(CompanionPackCatalog.ABLITERATED_17B_ID, pack.id)
        assertEquals(CompanionPackCatalog.ABLITERATED_17B_ID, CompanionPackCatalog.builtIn.first().id)
        assertEquals("6fb5977ef935e2a54c0bd5ec45e841d5ba4256b2223c25b4f707553abac8f448", pack.sha256)
        assertEquals(1_107_409_024L, pack.sizeBytes)
        assertTrue(pack.url.startsWith("https://huggingface.co/mradermacher/Qwen3-1.7B-abliterated-GGUF/resolve/"))
        assertFalse(pack.url.contains("/resolve/main/"))
        assertTrue(CompanionPackCatalog.isAbliteratedCandidate(pack))
        assertEquals(1, CompanionPackCatalog.builtIn.count { it.recommended })
        assertEquals(7, CompanionPackCatalog.builtIn.size)
    }

    @Test fun offgridRejectsInstructAndReplacedWeights() {
        val q4 = CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.ABLITERATED_17B_ID }
        assertTrue(CompanionPackCatalog.isVerifiedMinimalRefusal(q4))
        assertFalse(CompanionPackCatalog.isVerifiedMinimalRefusal(q4.copy(sha256 = "f".repeat(64))))
        assertFalse(CompanionPackCatalog.isVerifiedMinimalRefusal(CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.INSTRUCT_15B_ID }))
    }

    @Test fun lowMemoryPacksKeepBoundedContextOnLargePhones() {
        assertEquals(2048, DeviceInferenceGuard.contextTokens(6000, 2048))
        assertEquals(2048, DeviceInferenceGuard.contextTokens(6000, 1792))
        val q3 = CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.ABLITERATED_17B_Q3_ID }
        assertEquals(939_538_560L, q3.sizeBytes)
        assertTrue(q3.minRamMb < 2048)
        assertFalse(q3.url.contains("/main/"))
    }

    @Test
    fun allBuiltInRowsAreLegalAndOptIn4bNeedsMoreRam() {
        CompanionPackCatalog.builtIn.forEach { pack ->
            assertTrue(pack.id, CompanionPackCatalog.isLegalAllowlistRow(pack))
            assertTrue(pack.id, pack.sha256.all { it in "0123456789abcdef" })
        }
        val big = CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.ABLITERATED_4B_ID }
        val small = CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.HERETIC_2B_ID }
        assertFalse(big.recommended)
        assertEquals("1ec0b30c75b49223c82542caf2635a7af4edcda80d8c89759cc000d3871bf48e", big.sha256)
        assertEquals(2_707_514_688L, big.sizeBytes)
        assertTrue(big.minRamMb > small.minRamMb)
        // Label must state the same free-RAM floor the guard enforces.
        assertEquals(4608, big.minRamMb)
        assertTrue(big.label.contains("4.5 GB free RAM"))
    }
}
