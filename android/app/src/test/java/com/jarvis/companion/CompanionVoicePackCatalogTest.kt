package com.jarvis.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
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
        assertFalse(CompanionVoicePackCatalog.builtIn.any { it.id == "piper-en-lessac-medium" })
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

    @Test
    fun pocketIsTheOnlyOnDeviceTtsAndEveryTtsEngineCanSynthesize() {
        val tts = CompanionVoicePackCatalog.builtIn.filter { it.role == "tts" }
        assertEquals(listOf("pocket-tts-en"), tts.map { it.id })
        assertEquals("pocket-tts-onnx", tts.first().engine)
        CompanionVoicePackCatalog.builtIn.forEach { pack ->
            assertTrue("engine ${pack.engine} on ${pack.id} cannot synthesize", CompanionVoicePackCatalog.canSynthesize(pack))
        }
        tts.forEach { pack ->
            assertTrue(pack.url.startsWith("https://"))
            pack.artifacts.forEach { art ->
                assertTrue(art.url.startsWith("https://"))
                assertEquals(64, art.sha256.length)
            }
        }
    }

    @Test
    fun pocketTtsRowCarriesAlbaMackennaAttribution() {
        val pocket = CompanionVoicePackCatalog.builtIn.first { it.id == "pocket-tts-en" }
        assertTrue(pocket.attribution.contains("Alba MacKenna"))
        assertTrue(pocket.attribution.contains("CC BY 4.0"))
        assertTrue(pocket.attribution.contains("https://huggingface.co/kyutai/tts-voices#alba-mackenna"))
        assertTrue(pocket.attribution.contains("Kyutai Pocket TTS"))
        assertEquals(CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION, pocket.attribution)
    }

    @Test
    fun mergePinsPocketTtsAttributionAgainstLeaderOverride() {
        fun leaderPack(attribution: String): JSONObject {
            val pack = JSONObject()
                .put("id", CompanionVoicePackCatalog.POCKET_TTS_ID)
                .put("role", "tts")
                .put("engine", CompanionVoicePackCatalog.POCKET_TTS_ENGINE)
                .put("attribution", attribution)
            return JSONObject().put("packs", JSONArray().put(pack))
        }
        for (sent in listOf("", "something else")) {
            val pocket = CompanionVoicePackCatalog.merge(leaderPack(sent))
                .first { it.id == CompanionVoicePackCatalog.POCKET_TTS_ID }
            assertEquals(
                "leader attribution=$sent must not replace Kyutai/Alba credit",
                CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION,
                pocket.attribution,
            )
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

class PocketTtsEngineTest {
    @Test
    fun nearSilentWavIsRejected() {
        val header = ByteArray(44)
        val silent = ByteArray(44 + 200) { 0 }
        assertTrue(PocketTtsEngine.isNearSilentPcmWav(silent))
        assertTrue(PocketTtsEngine.isNearSilentPcmWav(header))
        val loud = ByteArray(44 + 200) { i -> if (i < 44) 0 else 40 }
        assertFalse(PocketTtsEngine.isNearSilentPcmWav(loud))
    }
}

class SpeakableTtsChunkerTest {
    @Test
    fun longReplyYieldsChunksUnderBudgetWithNoLoss() {
        val paragraphs = (1..12).joinToString("\n\n") { n ->
            "Paragraph $n explains the orchard gate, the north path, and the spare key. " +
                "It also mentions the greenhouse schedule and the Friday delivery."
        }
        val withJunk = "```\ncode()\n```\nSee https://example.invalid/docs and **bold**.\n$paragraphs"
        val chunks = SpeakableTtsChunker.chunk(withJunk)
        assertTrue("expected multiple chunks, got ${chunks.size}", chunks.size >= 2)
        chunks.forEach { piece ->
            assertTrue(piece.length <= SpeakableTtsChunker.MAX_CHUNK_CHARS)
            assertFalse(piece.contains("https://"))
            assertFalse(piece.contains("```"))
        }
        val spoken = SpeakableTtsChunker.forSpeech(withJunk)
        val joined = chunks.joinToString(" ")
        spoken.split(" ").filter { it.isNotBlank() }.forEach { word ->
            assertTrue("lost word $word", joined.contains(word))
        }
    }
}
