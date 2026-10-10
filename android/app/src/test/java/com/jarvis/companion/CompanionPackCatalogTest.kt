package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionPackCatalogTest {
    @Test
    fun builtInRecommendedPackHasPinnedUrlAndHash() {
        val pack = CompanionPackCatalog.builtIn.first { it.recommended }
        assertTrue(pack.url.startsWith("https://"))
        assertTrue(pack.sha256.isNotBlank())
        assertTrue(pack.sha256.length == 64)
        assertTrue(pack.sha256 != "0000000000000000000000000000000000000000000000000000000000000000")
        assertTrue(pack.sizeBytes > 1_000_000_000L)
        assertEquals("qwen2.5-1.5b-instruct-q4", pack.id)
        assertEquals(
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
            pack.url,
        )
        assertEquals("6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e", pack.sha256)
        assertFalse(CompanionPackCatalog.builtIn.any { CompanionPackCatalog.isAbliteratedCandidate(it) })
        assertEquals(2, CompanionPackCatalog.builtIn.size)
    }
}
