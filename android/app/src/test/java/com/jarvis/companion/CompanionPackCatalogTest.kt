package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionPackCatalogTest {
    @Test
    fun builtInRecommendedPackIsPinnedHereticDefault() {
        val pack = CompanionPackCatalog.builtIn.first { it.recommended }
        assertEquals(CompanionPackCatalog.HERETIC_2B_ID, pack.id)
        assertEquals(CompanionPackCatalog.HERETIC_2B_ID, CompanionPackCatalog.builtIn.first().id)
        assertEquals("dad8a69dddcd64f2221dd06ae5c46baceb31ed9bd0dec330306d77762c377cf1", pack.sha256)
        assertEquals(1_270_807_936L, pack.sizeBytes)
        assertTrue(pack.url.startsWith("https://huggingface.co/jordanwoodson/Qwen3.5-2B-heretic-GGUF/resolve/"))
        assertFalse(pack.url.contains("/resolve/main/"))
        assertTrue(CompanionPackCatalog.isAbliteratedCandidate(pack))
        assertEquals(1, CompanionPackCatalog.builtIn.count { it.recommended })
        assertEquals(4, CompanionPackCatalog.builtIn.size)
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
