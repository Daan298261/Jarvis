package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

@RunWith(RobolectricTestRunner::class)
class CompanionVoicePackManagerTest {
    private lateinit var context: Context
    private lateinit var manager: CompanionVoicePackManager

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        manager = CompanionVoicePackManager(context)
        context.getSharedPreferences("companion_voice_pack", Context.MODE_PRIVATE).edit().clear().apply()
        File(context.filesDir, "voice-packs").deleteRecursively()
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
