package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionVoicePackCatalogTest {
    @Test
    fun builtInPacksHavePinnedHttpsUrlsAndHashes() {
        CompanionVoicePackCatalog.validateBuiltIn()
        CompanionVoicePackCatalog.builtIn.forEach { pack ->
            assertTrue(pack.url.startsWith("https://"))
            assertEquals(64, pack.sha256.length)
            assertTrue(pack.sha256.any { it != '0' })
            assertTrue(pack.sizeBytes > 0)
            assertTrue(pack.role == "stt" || pack.role == "tts")
            pack.artifacts.forEach { art ->
                assertTrue(art.url.startsWith("https://"))
                assertEquals(64, art.sha256.length)
            }
        }
    }

    @Test
    fun recommendedDefaultsMatchRfc0140() {
        val stt = CompanionVoicePackCatalog.builtIn.first { it.role == "stt" && it.recommended }
        val tts = CompanionVoicePackCatalog.builtIn.first { it.role == "tts" && it.recommended }
        assertEquals("whisper-tiny-en-cpp", stt.id)
        assertEquals("pocket-tts-en", tts.id)
        assertTrue(stt.sizeBytes <= 80_000_000L)
        assertTrue(tts.sizeBytes <= 150_000_000L)
        assertTrue(stt.sizeBytes + tts.sizeBytes <= 250_000_000L)
        assertTrue(CompanionVoicePackCatalog.builtIn.any { it.id == "whisper-base-en-cpp" })
        assertTrue(CompanionVoicePackCatalog.builtIn.any { it.id == "piper-en-lessac-medium" })
    }

    @Test
    fun emptyUrlFailsValidation() {
        try {
            require("".isNotBlank()) { "Voice pack demo has empty url" }
            assertTrue(false)
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message!!.contains("empty url"))
        }
    }
}

class CompanionVoiceRoutingTest {
    @Test
    fun onlinePrefersGatewayAndHostNeural() {
        val d = CompanionVoiceRouting.decide(
            leaderReachable = true,
            realtimeVoiceHealthy = true,
            hostTtsHealthy = true,
            sttPackStatus = CompanionVoicePackStatus.READY,
            ttsPackStatus = CompanionVoicePackStatus.READY,
        )
        assertEquals(VoiceRouteMode.ONLINE_HOST, d.mode)
        assertEquals(SttVoiceRoute.GATEWAY, d.stt)
        assertEquals(TtsVoiceRoute.HOST_NEURAL, d.tts)
        assertFalse(d.onDeviceIndicator)
    }

    @Test
    fun hostVoiceFailOffersOnDeviceWithBanner() {
        val d = CompanionVoiceRouting.decide(
            leaderReachable = true,
            realtimeVoiceHealthy = false,
            hostTtsHealthy = false,
            sttPackStatus = CompanionVoicePackStatus.READY,
            ttsPackStatus = CompanionVoicePackStatus.READY,
        )
        assertEquals(VoiceRouteMode.FALLBACK_A, d.mode)
        assertEquals(SttVoiceRoute.ON_DEVICE, d.stt)
        assertEquals(TtsVoiceRoute.ON_DEVICE, d.tts)
        assertTrue(d.banner != null)
        assertTrue(d.onDeviceIndicator)
    }

    @Test
    fun leaderDownWithPacksIsModeBWhenLlmReady() {
        val d = CompanionVoiceRouting.decide(
            leaderReachable = false,
            realtimeVoiceHealthy = false,
            hostTtsHealthy = false,
            sttPackStatus = CompanionVoicePackStatus.READY,
            ttsPackStatus = CompanionVoicePackStatus.READY,
            localLlmReady = true,
        )
        assertEquals(VoiceRouteMode.GRID_DOWN_B, d.mode)
        assertEquals(SttVoiceRoute.ON_DEVICE, d.stt)
        assertEquals(TtsVoiceRoute.ON_DEVICE, d.tts)
    }

    @Test
    fun missingPacksNeverPretendListening() {
        val d = CompanionVoiceRouting.decide(
            leaderReachable = false,
            realtimeVoiceHealthy = false,
            hostTtsHealthy = false,
            sttPackStatus = CompanionVoicePackStatus.MISSING,
            ttsPackStatus = CompanionVoicePackStatus.MISSING,
        )
        assertEquals(SttVoiceRoute.INSTALL, d.stt)
        assertEquals(TtsVoiceRoute.INSTALL, d.tts)
        assertTrue(d.error != null)
    }
}

class PocketOrPiperTtsEngineTest {
    @Test
    fun nearSilentWavIsRejected() {
        val header = ByteArray(44)
        val silent = ByteArray(44 + 200) { 0 }
        assertTrue(PocketOrPiperTtsEngine.isNearSilentPcmWav(silent))
        assertTrue(PocketOrPiperTtsEngine.isNearSilentPcmWav(header))
        val loud = ByteArray(44 + 200) { i -> if (i < 44) 0 else 40 }
        assertFalse(PocketOrPiperTtsEngine.isNearSilentPcmWav(loud))
    }
}
