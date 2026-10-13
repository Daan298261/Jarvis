package com.jarvis.companion

import android.app.Application
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.Voice
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowTextToSpeech
import java.util.Locale

/** RFC-0216 S4: PlatformVoice applies ANZU's voice language to the real TextToSpeech path. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PlatformVoiceTtsTest {
    private val app: Application = ApplicationProvider.getApplicationContext()
    private lateinit var previous: Locale

    @Before fun dutchPhone() { previous = Locale.getDefault(); Locale.setDefault(Locale.forLanguageTag("nl-NL")) }
    @After fun restore() { Locale.setDefault(previous); ShadowTextToSpeech.reset() }

    private fun voice(name: String, tag: String, quality: Int = Voice.QUALITY_HIGH) =
        Voice(name, Locale.forLanguageTag(tag), quality, Voice.LATENCY_NORMAL, false, emptySet())

    private fun started(setting: VoiceLanguageSetting = VoiceLanguageSetting()): Pair<PlatformVoice, List<Boolean>> {
        val ready = mutableListOf<Boolean>()
        val pv = PlatformVoice(app, language = { setting }, onTtsReady = { ready += it })
        assertTrue(pv.voicesFor().isEmpty()) // before init: nothing claimed
        shadowOf(ShadowTextToSpeech.getLastTextToSpeechInstance()).onInitListener.onInit(TextToSpeech.SUCCESS)
        shadowOf(Looper.getMainLooper()).idle()
        return pv to ready
    }

    @Test fun dutch_locale_phone_speaks_with_english_voice() {
        ShadowTextToSpeech.addVoice(voice("nl-nl-x-lfc-local", "nl-NL", Voice.QUALITY_VERY_HIGH))
        ShadowTextToSpeech.addVoice(voice("en-us-x-iol-local", "en-US"))
        val (pv, ready) = started()
        assertEquals(listOf(true), ready)
        assertTrue(pv.supportsLanguage())
        val errors = mutableListOf<String>()
        pv.speak("Hello Taco.", onDone = {}, onError = { errors += it })
        val shadow = shadowOf(ShadowTextToSpeech.getLastTextToSpeechInstance())
        assertTrue(errors.isEmpty())
        assertEquals("en-us-x-iol-local", shadow.currentVoice.name)
        assertEquals("Hello Taco.", shadow.lastSpokenText)
    }

    @Test fun only_dutch_voices_returns_missing_voice_and_does_not_speak() {
        ShadowTextToSpeech.addVoice(voice("nl-nl-x-lfc-local", "nl-NL"))
        val (pv, _) = started()
        assertFalse(pv.supportsLanguage())
        val errors = mutableListOf<String>()
        pv.speak("Hello Taco.", onDone = {}, onError = { errors += it })
        val shadow = shadowOf(ShadowTextToSpeech.getLastTextToSpeechInstance())
        assertEquals(listOf(VoiceLanguagePrefs.missingVoiceMessage(VoiceLanguageSetting())), errors)
        assertNull(shadow.lastSpokenText)
        assertNull(shadow.currentVoice)
    }

    @Test fun explicit_voice_choice_is_applied() {
        ShadowTextToSpeech.addVoice(voice("en-us-x-iol-local", "en-US"))
        ShadowTextToSpeech.addVoice(voice("en-gb-x-rjs-local", "en-GB", Voice.QUALITY_NORMAL))
        val (pv, _) = started(VoiceLanguageSetting("en", "en-gb-x-rjs-local"))
        pv.speak("Hi.", onDone = {}, onError = { fail(it) })
        assertEquals("en-gb-x-rjs-local", shadowOf(ShadowTextToSpeech.getLastTextToSpeechInstance()).currentVoice.name)
    }
}
