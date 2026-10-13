package com.jarvis.companion

import android.speech.SpeechRecognizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OfflineVoiceFallbackTest {
    private fun offline(stt: String, tts: String, platformStt: Boolean, platformTts: Boolean) = CompanionVoiceRouting.decide(
        leaderReachable = false,
        realtimeVoiceHealthy = false,
        hostTtsHealthy = false,
        sttPackStatus = stt,
        ttsPackStatus = tts,
        localLlmReady = true,
        platformSttAvailable = platformStt,
        platformTtsAvailable = platformTts,
    )

    @Test
    fun anzuPacksWinOverAndroidEngines() {
        val d = offline(CompanionVoicePackStatus.READY, CompanionVoicePackStatus.READY, platformStt = true, platformTts = true)
        assertEquals(SttVoiceRoute.ON_DEVICE, d.stt)
        assertEquals(TtsVoiceRoute.ON_DEVICE, d.tts)
        assertEquals("On-device voice (ANZU desktop unreachable)", d.banner)
    }

    @Test
    fun androidEnginesCoverPhoneWithoutPacks() {
        val d = offline(CompanionVoicePackStatus.MISSING, CompanionVoicePackStatus.MISSING, platformStt = true, platformTts = true)
        assertEquals(VoiceRouteMode.GRID_DOWN_B, d.mode)
        assertEquals(SttVoiceRoute.PLATFORM, d.stt)
        assertEquals(TtsVoiceRoute.PLATFORM, d.tts)
        assertNull(d.error)
        assertTrue(d.onDeviceIndicator)
        assertTrue(d.banner!!.contains("built-in voice"))
    }

    @Test
    fun mixedPackAndPlatform() {
        val d = offline(CompanionVoicePackStatus.READY, CompanionVoicePackStatus.MISSING, platformStt = false, platformTts = true)
        assertEquals(SttVoiceRoute.ON_DEVICE, d.stt)
        assertEquals(TtsVoiceRoute.PLATFORM, d.tts)
    }

    @Test
    fun nothingAvailableStillAsksForInstall() {
        val d = offline(CompanionVoicePackStatus.MISSING, CompanionVoicePackStatus.MISSING, platformStt = false, platformTts = false)
        assertEquals(SttVoiceRoute.INSTALL, d.stt)
        assertEquals(TtsVoiceRoute.INSTALL, d.tts)
        assertTrue(d.error!!.contains("More → Voice"))
    }

    @Test
    fun hostVoiceFailureFallsBackToPlatform() {
        val d = CompanionVoiceRouting.decide(
            leaderReachable = true,
            realtimeVoiceHealthy = false,
            hostTtsHealthy = false,
            sttPackStatus = CompanionVoicePackStatus.MISSING,
            ttsPackStatus = CompanionVoicePackStatus.MISSING,
            platformSttAvailable = true,
            platformTtsAvailable = true,
        )
        assertEquals(VoiceRouteMode.FALLBACK_A, d.mode)
        assertEquals(SttVoiceRoute.PLATFORM, d.stt)
        assertTrue(d.banner!!.contains("built-in voice"))
    }

    @Test
    fun onlineHostStillPreferredWhenHealthy() {
        val d = CompanionVoiceRouting.decide(
            leaderReachable = true,
            realtimeVoiceHealthy = true,
            hostTtsHealthy = true,
            sttPackStatus = CompanionVoicePackStatus.MISSING,
            ttsPackStatus = CompanionVoicePackStatus.MISSING,
            platformSttAvailable = true,
            platformTtsAvailable = true,
        )
        assertEquals(SttVoiceRoute.GATEWAY, d.stt)
        assertEquals(TtsVoiceRoute.HOST_NEURAL, d.tts)
    }

    @Test
    fun voiceRepliesAreSpokenWithPlatformTts() {
        assertTrue(StandaloneMode.shouldSpeakVoiceReply(fromVoice = true, ttsRoute = TtsVoiceRoute.PLATFORM))
        assertFalse(StandaloneMode.shouldSpeakVoiceReply(fromVoice = false, ttsRoute = TtsVoiceRoute.PLATFORM))
    }

    @Test
    fun recognizerErrorsAreExplained() {
        assertTrue(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_NETWORK).contains("offline speech pack"))
        assertTrue(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_NO_MATCH).contains("didn't catch"))
        assertTrue(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS).contains("Microphone"))
        assertTrue(PlatformVoice.errorCopy(999).contains("999"))
    }

    @Test
    fun noteBodyDropsTheCue() {
        assertEquals("buy milk", StandaloneMode.noteBody("Take a note: buy milk"))
        assertEquals("the gate code is 4412", StandaloneMode.noteBody("remember this, the gate code is 4412"))
        assertEquals("the gate code is 4412", StandaloneMode.noteBody("the gate code is 4412 — remember this"))
        assertEquals("plain text", StandaloneMode.noteBody("plain text"))
    }
}
