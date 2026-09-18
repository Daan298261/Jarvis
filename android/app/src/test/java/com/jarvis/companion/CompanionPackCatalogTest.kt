package com.jarvis.companion

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
    }
}
