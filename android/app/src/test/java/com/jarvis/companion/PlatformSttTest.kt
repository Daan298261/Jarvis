package com.jarvis.companion

import android.Manifest
import android.app.Application
import android.content.Intent
import android.content.pm.ResolveInfo
import android.content.pm.ServiceInfo
import android.os.Bundle
import android.os.Looper
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSpeechRecognizer
import java.util.Locale

/** RFC-0216 S3: Samsung S23 platform STT must fall through to a working recognizer and fail loudly otherwise. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PlatformSttTest {
    @Test
    fun silenceStopsAt250MsAndMissingFinalCommitsPartialOnce() {
        shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
        ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
        val voice = PlatformVoice(app)
        val spoken = mutableListOf<String>()
        var ended = 0
        voice.startListening({}, { spoken += it }, { throw AssertionError(it) }, { ended++ })
        idle()
        val recognizer = shadowOf(ShadowSpeechRecognizer.getLatestSpeechRecognizer())
        recognizer.triggerOnPartialResults(results("Open my project"))
        idle()
        recognizer.triggerOnRmsChanged(0f)
        idle()
        shadowOf(Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(249))
        assertTrue(voice.listening)
        shadowOf(Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(1))
        assertFalse(voice.listening)
        assertEquals(1, ended)
        shadowOf(Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(VoiceEndpoint.FINAL_RESULT_MS))
        assertEquals(listOf("Open my project"), spoken)
        recognizer.triggerOnResults(results("Late duplicate"))
        idle()
        assertEquals(1, spoken.size)
        voice.shutdown()
    }

    @Test
    fun noSpeechDeadlineReleasesRecognizerAndReportsError() {
        shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
        ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
        val voice = PlatformVoice(app)
        val errors = mutableListOf<String>()
        voice.startListening({}, { throw AssertionError("Unexpected result") }, { errors += it })
        idle()
        val recognizer = shadowOf(ShadowSpeechRecognizer.getLatestSpeechRecognizer())
        shadowOf(Looper.getMainLooper()).idleFor(java.time.Duration.ofMillis(VoiceEndpoint.NO_SPEECH_MS))
        assertFalse(voice.listening)
        assertTrue(recognizer.isDestroyed)
        assertEquals(1, errors.size)
        voice.shutdown()
    }
    private val app: Application = ApplicationProvider.getApplicationContext()

    @After
    fun resetShadow() = ShadowSpeechRecognizer.reset()

    private fun installDefaultRecognizer() {
        val info = ResolveInfo().apply {
            serviceInfo = ServiceInfo().apply { packageName = "com.google.android.tts"; name = "FakeRecognitionService" }
        }
        shadowOf(app.packageManager).addResolveInfoForIntent(Intent(RecognitionService.SERVICE_INTERFACE), info)
    }

    private fun results(vararg text: String) = Bundle().apply {
        putStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION, arrayListOf(*text))
    }

    private fun idle() = shadowOf(Looper.getMainLooper()).idle()

    @Test
    fun onDeviceLanguageUnavailableFallsThroughToDefaultRecognizerAndTranscribes() {
        shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
        ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
        installDefaultRecognizer()
        val voice = PlatformVoice(app)
        val errors = mutableListOf<String>()
        val transcripts = mutableListOf<String>()
        voice.startListening(onPartial = {}, onResult = { transcripts += it }, onError = { errors += it })
        idle()
        val onDevice = ShadowSpeechRecognizer.getLatestSpeechRecognizer()
        shadowOf(onDevice).triggerOnError(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE)
        idle()
        val fallback = ShadowSpeechRecognizer.getLatestSpeechRecognizer()
        assertNotSame(onDevice, fallback)
        assertTrue(voice.listening)
        shadowOf(fallback).triggerOnResults(results("what's the weather tomorrow"))
        idle()
        assertEquals(emptyList<String>(), errors)
        assertEquals(listOf("what's the weather tomorrow"), transcripts)
        assertFalse(voice.listening)
        voice.shutdown()
    }

    @Test
    fun languageUnavailableWithNoOtherRecognizerIsAnExplicitError() {
        shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
        ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
        val voice = PlatformVoice(app)
        val errors = mutableListOf<String>()
        var results = 0
        voice.startListening(onPartial = {}, onResult = { results++ }, onError = { errors += it })
        idle()
        shadowOf(ShadowSpeechRecognizer.getLatestSpeechRecognizer()).triggerOnError(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE)
        idle()
        assertEquals(0, results)
        assertEquals(listOf(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE, "en-US")), errors)
        assertFalse(voice.listening)
        voice.shutdown()
    }

    @Test
    fun blankRecognizerResultIsNeverASuccess() {
        shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
        ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
        val voice = PlatformVoice(app)
        val errors = mutableListOf<String>()
        var results = 0
        voice.startListening(onPartial = {}, onResult = { results++ }, onError = { errors += it })
        idle()
        shadowOf(ShadowSpeechRecognizer.getLatestSpeechRecognizer()).triggerOnResults(results("   "))
        idle()
        assertEquals(0, results)
        assertEquals(listOf(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_NO_MATCH, "en-US")), errors)
        voice.shutdown()
    }

    @Test
    fun onDeviceIsTriedFirstThenDefault() {
        assertEquals(
            listOf(PlatformRecognizerKind.ON_DEVICE, PlatformRecognizerKind.DEFAULT),
            PlatformSttPlan.candidates(onDeviceAvailable = true, defaultAvailable = true),
        )
        assertEquals(listOf(PlatformRecognizerKind.DEFAULT), PlatformSttPlan.candidates(false, true))
        assertTrue(PlatformSttPlan.candidates(false, false).isEmpty())
    }

    @Test
    fun samsungOnDeviceLanguageFailuresFallBackToDefaultRecognizer() {
        for (code in listOf(
            SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED,
            SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE,
            SpeechRecognizer.ERROR_CANNOT_CHECK_SUPPORT,
            SpeechRecognizer.ERROR_SERVER_DISCONNECTED,
            SpeechRecognizer.ERROR_CLIENT,
        )) {
            assertTrue("code $code", PlatformSttPlan.shouldFallBack(code, heardSpeech = false, hasNext = true))
            assertFalse("no next recognizer for $code", PlatformSttPlan.shouldFallBack(code, heardSpeech = false, hasNext = false))
            assertFalse("speech already heard for $code", PlatformSttPlan.shouldFallBack(code, heardSpeech = true, hasNext = true))
        }
    }

    @Test
    fun ownerFacingErrorsAreNotRetriedSilently() {
        for (code in listOf(
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS,
            SpeechRecognizer.ERROR_NO_MATCH,
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
            SpeechRecognizer.ERROR_AUDIO,
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY,
        )) {
            assertFalse("code $code", PlatformSttPlan.shouldFallBack(code, heardSpeech = false, hasNext = true))
        }
    }

    @Test
    fun dutchDeviceLocaleStillSendsTheProviderLanguageToTheRecognizer() {
        val saved = Locale.getDefault()
        Locale.setDefault(Locale.forLanguageTag("nl-NL"))
        try {
            shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
            ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
            val voice = PlatformVoice(app, sttLanguage = SttLanguageSource { "en-GB" })
            voice.startListening(onPartial = {}, onResult = {}, onError = {})
            idle()
            val intent = shadowOf(ShadowSpeechRecognizer.getLatestSpeechRecognizer()).lastRecognizerIntent
            assertEquals("en-GB", intent.getStringExtra(RecognizerIntent.EXTRA_LANGUAGE))
            voice.shutdown()

            val defaultVoice = PlatformVoice(app)
            defaultVoice.startListening(onPartial = {}, onResult = {}, onError = {})
            idle()
            val defaultIntent = shadowOf(ShadowSpeechRecognizer.getLatestSpeechRecognizer()).lastRecognizerIntent
            assertEquals("en-US", defaultIntent.getStringExtra(RecognizerIntent.EXTRA_LANGUAGE))
            defaultVoice.shutdown()
        } finally {
            Locale.setDefault(saved)
        }
    }

    @Test
    fun languagePackCopyIsBuiltFromTheActualTag() {
        assertTrue(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE, "nl-NL").contains("Dutch (Netherlands)"))
        assertTrue(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED, "en-US").contains("English (United States)"))
    }

    @Test
    fun restartIgnoresStaleCallbacksFromThePreviousSession() {
        shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
        ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
        installDefaultRecognizer()
        val voice = PlatformVoice(app)
        val errors = mutableListOf<String>()
        val transcripts = mutableListOf<String>()
        voice.startListening(onPartial = {}, onResult = { transcripts += "first:$it" }, onError = { errors += "first:$it" })
        idle()
        val first = ShadowSpeechRecognizer.getLatestSpeechRecognizer()
        voice.startListening(onPartial = {}, onResult = { transcripts += it }, onError = { errors += it })
        idle()
        val second = ShadowSpeechRecognizer.getLatestSpeechRecognizer()
        assertNotSame(first, second)

        // The first recognizer delivers late: a fallback-eligible error and a result. Both must be ignored.
        shadowOf(first).triggerOnError(SpeechRecognizer.ERROR_CLIENT)
        shadowOf(first).triggerOnResults(results("stale words"))
        idle()
        assertSame("no extra fallback recognizer was created", second, ShadowSpeechRecognizer.getLatestSpeechRecognizer())
        assertTrue(voice.listening)

        // The live session still falls back exactly once and transcribes.
        shadowOf(second).triggerOnError(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE)
        idle()
        val fallback = ShadowSpeechRecognizer.getLatestSpeechRecognizer()
        assertNotSame(second, fallback)
        shadowOf(second).triggerOnError(SpeechRecognizer.ERROR_CLIENT)
        idle()
        assertSame("a stale error from the replaced recognizer must not fall back again", fallback, ShadowSpeechRecognizer.getLatestSpeechRecognizer())
        shadowOf(fallback).triggerOnResults(results("hello anzu"))
        idle()
        assertEquals(emptyList<String>(), errors)
        assertEquals(listOf("hello anzu"), transcripts)
        voice.shutdown()
    }

    @Test
    fun samsungLanguageAndBindingErrorsHaveActionableCopy() {
        for (code in listOf(
            SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED,
            SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE,
            SpeechRecognizer.ERROR_SERVER_DISCONNECTED,
            SpeechRecognizer.ERROR_CANNOT_CHECK_SUPPORT,
            SpeechRecognizer.ERROR_TOO_MANY_REQUESTS,
        )) {
            assertFalse("code $code", PlatformVoice.errorCopy(code, "en-US").contains("(code"))
        }
        assertTrue(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE, "en-US").contains("English (United States)"))
    }

    @Test
    fun permissionDeniedIsAnExplicitError() {
        shadowOf(app).denyPermissions(Manifest.permission.RECORD_AUDIO)
        val voice = PlatformVoice(app)
        val errors = mutableListOf<String>()
        var results = 0
        voice.startListening(onPartial = {}, onResult = { results++ }, onError = { errors += it })
        shadowOf(Looper.getMainLooper()).idle()
        assertEquals(0, results)
        assertEquals(listOf(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS, "en-US")), errors)
        assertTrue(errors.single().contains("Microphone"))
        assertFalse(voice.listening)
        voice.shutdown()
    }

    @Test
    fun recognizerUnavailableIsAnExplicitError() {
        shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
        ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(false)
        val voice = PlatformVoice(app)
        assertFalse(voice.sttAvailable())
        val errors = mutableListOf<String>()
        var results = 0
        voice.startListening(onPartial = {}, onResult = { results++ }, onError = { errors += it })
        assertEquals(0, results)
        assertEquals(listOf(PlatformSttPlan.NO_RECOGNIZER_COPY), errors)
        assertFalse(voice.listening)
        voice.shutdown()
    }

    /** RFC-0216 S4: the voice-language setting (single source) drives EXTRA_LANGUAGE, bare tags get a region. */
    @Test
    fun voiceLanguageSettingDrivesRecognizerLanguage() {
        val saved = Locale.getDefault()
        Locale.setDefault(Locale.forLanguageTag("nl-NL"))
        try {
            shadowOf(app).grantPermissions(Manifest.permission.RECORD_AUDIO)
            ShadowSpeechRecognizer.setIsOnDeviceRecognitionAvailable(true)
            for ((setting, expected) in listOf(
                VoiceLanguageSetting() to "en-US",
                VoiceLanguageSetting("en-GB") to "en-GB",
                VoiceLanguageSetting("en", sttLanguageOverride = "nl") to "nl-NL",
            )) {
                val voice = PlatformVoice(app, language = { setting })
                voice.startListening(onPartial = {}, onResult = {}, onError = {})
                idle()
                val intent = shadowOf(ShadowSpeechRecognizer.getLatestSpeechRecognizer()).lastRecognizerIntent
                assertEquals(expected, intent.getStringExtra(RecognizerIntent.EXTRA_LANGUAGE))
                voice.shutdown()
            }
        } finally {
            Locale.setDefault(saved)
        }
    }
}
