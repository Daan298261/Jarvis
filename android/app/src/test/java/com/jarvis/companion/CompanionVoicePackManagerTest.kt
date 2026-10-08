package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
class CompanionVoicePackManagerTest {
    private lateinit var context: Context
    private lateinit var manager: CompanionVoicePackManager

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("companion_voice_pack", Context.MODE_PRIVATE).edit().clear().apply()
        context.getSharedPreferences("companion_voice_digest", Context.MODE_PRIVATE).edit().clear().apply()
        File(context.filesDir, "voice-packs").deleteRecursively()
        manager = CompanionVoicePackManager(context)
    }

    @Test
    fun hashMismatchLeavesPackNotReady() {
        val pack = manager.selectedSttPack()!!
        val art = pack.artifacts.first()
        val target = manager.artifactFile(pack, art)
        target.parentFile?.mkdirs()
        target.writeBytes("corrupt-bytes-not-matching-sha".toByteArray())
        // refreshStatus is suspending — use runBlocking via kotlinx
        kotlinx.coroutines.runBlocking { manager.refreshStatus() }
        assertEquals(CompanionVoicePackStatus.ERROR, manager.sttStatus())
        assertTrue(manager.lastError().contains("Checksum") || manager.lastError().contains("mismatch"))
        assertFalse(manager.isSttReady())
    }

    @Test
    fun missingPackIsMissingNotReady() {
        kotlinx.coroutines.runBlocking { manager.refreshStatus() }
        assertEquals(CompanionVoicePackStatus.MISSING, manager.sttStatus())
        assertFalse(manager.isSttReady())
    }

    @Test
    fun missingNativeRuntimeFailsClosed() {
        val stt = WhisperCppSttEngine()
        assertFalse(stt.isRuntimeAvailable())
        val sttErr = stt.load("/missing.bin", "whisper.cpp")
        assertNotNull(sttErr)
        assertTrue(sttErr!!.contains("missing"))
        assertTrue(stt.transcribe(ByteArray(3200), 16_000).isFailure)

        val tts = PocketTtsEngine()
        assertFalse(tts.isRuntimeAvailable())
        val ttsErr = tts.load("/missing-pack", "pocket-tts-onnx")
        assertNotNull(ttsErr)
        assertTrue(ttsErr!!.contains("missing"))
        val silentAttempt = tts.synthesize("Hello from ANZU")
        assertTrue(silentAttempt.isFailure)
    }

    @Test
    fun synthesizeRejectsSilentStubSuccess() {
        val silentEngine = object : OnDeviceTtsEngine {
            override val runtimeName = "silent-stub"
            override fun isRuntimeAvailable() = true
            override fun load(packDirectory: String, engineId: String): String? = null
            override fun synthesize(text: String): Result<ByteArray> {
                val wav = ByteArray(44 + 400) { 0 }
                return Result.success(wav)
            }
            override fun unload() {}
        }
        val sttOk = object : OnDeviceSttEngine {
            override val runtimeName = "noop"
            override fun isRuntimeAvailable() = true
            override fun load(modelPath: String, engineId: String): String? = null
            override fun transcribe(pcm16le: ByteArray, sampleRate: Int) = Result.success("hello")
            override fun unload() {}
        }
        val local = CompanionVoicePackManager(context, sttEngine = sttOk, ttsEngine = silentEngine)
        val pack = local.selectedTtsPack()!!
        val arts = JSONArray()
        pack.artifacts.forEach { art ->
            val bytes = "fixture-${art.filename}".toByteArray()
            val target = local.artifactFile(pack, art)
            target.parentFile?.mkdirs()
            target.writeBytes(bytes)
            arts.put(
                JSONObject()
                    .put("filename", art.filename)
                    .put("url", art.url)
                    .put("sha256", sha256Hex(bytes))
                    .put("size_bytes", bytes.size.toLong()),
            )
        }
        local.updateCatalog(
            JSONObject().put(
                "packs",
                JSONArray().put(pack.toJson().put("artifacts", arts).put("sha256", sha256Hex(byteArrayOf(1)))),
            ),
        )
        val thrown = runCatching {
            kotlinx.coroutines.runBlocking { local.synthesize("Hello from ANZU") }
        }.exceptionOrNull()
        assertNotNull(thrown)
        assertTrue(thrown!!.message, thrown.message!!.contains("near-silent"))
    }

    @Test
    fun persistedPiperSelectionMigratesToPocket() {
        context.getSharedPreferences("companion_voice_pack", Context.MODE_PRIVATE)
            .edit()
            .putString("selected_tts_pack_id", "piper-en-lessac-medium")
            .apply()
        val migrated = CompanionVoicePackManager(context)
        assertEquals(CompanionVoicePackCatalog.POCKET_TTS_ID, migrated.selectedTtsPackId())
        assertEquals(
            CompanionVoicePackCatalog.POCKET_TTS_ID,
            context.getSharedPreferences("companion_voice_pack", Context.MODE_PRIVATE)
                .getString("selected_tts_pack_id", ""),
        )
        assertTrue(CompanionVoicePackCatalog.canSynthesize(migrated.selectedTtsPack()!!))
    }

    private fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}

@RunWith(RobolectricTestRunner::class)
class PostPairVoicePackOfferTest {
    private lateinit var context: Context

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("companion_ui", Context.MODE_PRIVATE).edit().clear().apply()
    }

    @Test
    fun shouldOfferUntilHandled() {
        val deviceId = "voice-device-1"
        assertTrue(
            PostPairVoicePackOfferPrefs.shouldOffer(
                context,
                deviceId,
                CompanionVoicePackStatus.MISSING,
                CompanionVoicePackStatus.MISSING,
            ),
        )
        PostPairVoicePackOfferPrefs.markHandled(context, deviceId)
        assertFalse(
            PostPairVoicePackOfferPrefs.shouldOffer(
                context,
                deviceId,
                CompanionVoicePackStatus.MISSING,
                CompanionVoicePackStatus.MISSING,
            ),
        )
    }
}
