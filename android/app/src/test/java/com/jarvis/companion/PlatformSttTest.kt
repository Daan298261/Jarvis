package com.jarvis.companion

import android.Manifest
import android.app.Application
import android.content.Intent
import android.content.pm.ResolveInfo
import android.content.pm.ServiceInfo
import android.os.Bundle
import android.os.Looper
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSpeechRecognizer

/** RFC-0216 S3: Samsung S23 platform STT must fall through to a working recognizer and fail loudly otherwise. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PlatformSttTest {
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
        assertEquals(listOf(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE)), errors)
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
        assertEquals(listOf(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_NO_MATCH)), errors)
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
    fun recognizerLanguageIsEnglishNotSystemLocale() {
        assertEquals("en-US", PlatformSttPlan.SPEECH_LANGUAGE_TAG)
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
            assertFalse("code $code", PlatformVoice.errorCopy(code).contains("(code"))
        }
        assertTrue(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE).contains("English"))
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
        assertEquals(listOf(PlatformVoice.errorCopy(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS)), errors)
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
}
