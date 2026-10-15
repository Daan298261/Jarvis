package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.Locale

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29])
class VoiceLanguageTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private val pocket = CompanionVoicePackCatalog.builtIn.first { it.id == CompanionVoicePackCatalog.POCKET_TTS_ID }

    private fun v(name: String, tag: String, quality: Int = 300, net: Boolean = false, notInstalled: Boolean = false) =
        TtsVoiceCandidate(name, Locale.forLanguageTag(tag), quality, 200, net, notInstalled)

    @Before fun clear() {
        context.getSharedPreferences(VoiceLanguagePrefs.PREFS, Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test fun defaults_to_product_english_not_system_locale() {
        val previous = Locale.getDefault()
        try {
            Locale.setDefault(Locale.forLanguageTag("nl-NL"))
            val s = VoiceLanguagePrefs.load(context)
            assertEquals("en", s.ttsLanguage)
            assertEquals("en", s.sttLanguage)
            assertEquals("", s.ttsVoiceName)
        } finally { Locale.setDefault(previous) }
    }

    @Test fun preference_persists_and_stt_override_is_independent() {
        assertTrue(VoiceLanguagePrefs.save(context, VoiceLanguageSetting("en-GB", "en-gb-x-rjs-local", "nl-NL")))
        val s = VoiceLanguagePrefs.load(context)
        assertEquals("en-GB", s.ttsLanguage)
        assertEquals("en-gb-x-rjs-local", s.ttsVoiceName)
        assertEquals("nl-NL", s.sttLanguage)
    }

    @Test fun changing_language_drops_voice_from_other_language() {
        val s = VoiceLanguageSetting("en-GB", "en-gb-x-rjs-local")
        assertEquals("en-gb-x-rjs-local", VoiceLanguagePrefs.withLanguage(s, "en-US").ttsVoiceName)
        assertEquals("", VoiceLanguagePrefs.withLanguage(s, "nl-NL").ttsVoiceName)
    }

    @Test fun dutch_phone_english_setting_never_picks_dutch_voice() {
        val voices = listOf(v("nl-nl-x-lfc-local", "nl-NL", quality = 500), v("en-us-x-sfg-network", "en-US", net = true),
            v("en-us-x-iol-local", "en-US"), v("en-gb-x-missing", "en-GB", quality = 500, notInstalled = true))
        assertEquals("en-us-x-iol-local", VoiceLanguagePrefs.pickVoice(voices, VoiceLanguageSetting("en"))!!.name)
        assertNull(VoiceLanguagePrefs.pickVoice(listOf(v("nl-nl-x-lfc-local", "nl-NL")), VoiceLanguageSetting("en")))
    }

    @Test fun explicit_voice_and_region_win_when_installed() {
        val voices = listOf(v("en-us-a", "en-US", 500), v("en-gb-b", "en-GB", 300), v("en-gb-c", "en-GB", 400))
        assertEquals("en-gb-c", VoiceLanguagePrefs.pickVoice(voices, VoiceLanguageSetting("en-GB"))!!.name)
        assertEquals("en-gb-b", VoiceLanguagePrefs.pickVoice(voices, VoiceLanguageSetting("en-GB", "en-gb-b"))!!.name)
        // A stale name from another language is ignored rather than forcing that language.
        assertEquals("en-us-a", VoiceLanguagePrefs.pickVoice(voices + v("nl-x", "nl-NL"), VoiceLanguageSetting("en", "nl-x"))!!.name)
    }

    @Test fun recognizer_tag_adds_region_to_bare_language() {
        assertEquals("en-US", VoiceLanguagePrefs.recognizerTag("en"))
        assertEquals("en-GB", VoiceLanguagePrefs.recognizerTag("en-GB"))
        assertEquals("nl-NL", VoiceLanguagePrefs.recognizerTag("nl"))
        assertEquals("it-IT", VoiceLanguagePrefs.recognizerTag("it"))
        assertEquals("en-US", VoiceLanguageSetting().recognizerLanguage)
        assertEquals("nl-NL", VoiceLanguageSetting("en", sttLanguageOverride = "nl").recognizerLanguage)
    }

    @Test fun fallback_notice_explains_recovery_without_native_paths() {
        val raw = "Load model /data/user/0/private/encoder.onnx failed: Unsupported model IR version: 13, max supported IR version: 10"
        val notice = OnDeviceTtsFallback.fallbackNotice(raw, "English")
        assertTrue(notice.contains("Update ANZU"))
        assertTrue(notice.contains("English"))
        assertFalse(notice.contains("/data/"))
        assertFalse(notice.contains("encoder.onnx"))
        assertTrue(notice.length < 180)
        assertFalse(OnDeviceTtsFallback.failureNotice("native stack trace").contains("native stack"))
        assertTrue(OnDeviceTtsFallback.failureNotice("Out of memory").contains("Close other apps"))
    }

    @Test fun pocket_pack_is_english_only_and_under_150_mb() {
        assertTrue(VoiceLanguagePrefs.packSpeaks(pocket, "en-GB"))
        assertFalse(VoiceLanguagePrefs.packSpeaks(pocket, "nl-NL"))
        assertFalse(VoiceLanguagePrefs.packSpeaks(null, "en"))
        assertTrue(pocket.sizeBytes <= 150_000_000L)
        assertEquals(pocket.sizeBytes, pocket.artifacts.sumOf { it.sizeBytes })
        pocket.artifacts.forEach { assertTrue(it.url.startsWith("https://")); assertEquals(64, it.sha256.length) }
    }

    @Test fun missing_voice_message_offers_download_for_english() {
        assertTrue(VoiceLanguagePrefs.missingVoiceMessage(VoiceLanguageSetting("en")).contains("More → Voice"))
        assertFalse(VoiceLanguagePrefs.missingVoiceMessage(VoiceLanguageSetting("nl-NL")).contains("Pocket"))
    }

    @Test fun fallback_speaks_only_unplayed_chunks_in_matching_language() {
        val chunks = listOf("One.", "Two.", "Three.")
        assertEquals("Two. Three.", OnDeviceTtsFallback.remainingText(chunks, 1))
        assertEquals("", OnDeviceTtsFallback.remainingText(chunks, 3))
        assertTrue(OnDeviceTtsFallback.shouldUsePlatform("Two.", platformSpeaksLanguage = true))
        assertFalse(OnDeviceTtsFallback.shouldUsePlatform("Two.", platformSpeaksLanguage = false))
        assertFalse(OnDeviceTtsFallback.shouldUsePlatform("", platformSpeaksLanguage = true))
    }

    private fun offline(ttsPack: String, platformTts: Boolean, packSpeaks: Boolean) = CompanionVoiceRouting.decide(
        leaderReachable = false, realtimeVoiceHealthy = false, hostTtsHealthy = false,
        sttPackStatus = CompanionVoicePackStatus.MISSING, ttsPackStatus = ttsPack, localLlmReady = true,
        platformSttAvailable = true, platformTtsAvailable = platformTts, ttsPackSpeaksLanguage = packSpeaks)

    @Test fun routing_uses_pack_only_for_its_language() {
        assertEquals(TtsVoiceRoute.ON_DEVICE, offline(CompanionVoicePackStatus.READY, true, true).tts)
        assertEquals(TtsVoiceRoute.PLATFORM, offline(CompanionVoicePackStatus.READY, true, false).tts)
    }

    @Test fun no_matching_voice_routes_to_install_not_wrong_accent() {
        // Dutch phone with no English system voice and no pack: download affordance, not a Dutch voice.
        val d = offline(CompanionVoicePackStatus.MISSING, platformTts = false, packSpeaks = true)
        assertEquals(TtsVoiceRoute.INSTALL, d.tts)
        assertNotNull(d.error)
    }

    @Test fun online_host_path_unchanged() {
        val d = CompanionVoiceRouting.decide(leaderReachable = true, realtimeVoiceHealthy = true, hostTtsHealthy = true,
            sttPackStatus = CompanionVoicePackStatus.MISSING, ttsPackStatus = CompanionVoicePackStatus.MISSING,
            ttsPackSpeaksLanguage = false)
        assertEquals(TtsVoiceRoute.HOST_NEURAL, d.tts)
    }
}
