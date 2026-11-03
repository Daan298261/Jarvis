package com.jarvis.companion

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.Locale
import java.util.UUID

private const val TAG = "PlatformVoice"

/**
 * Android's built-in SpeechRecognizer and TextToSpeech, used when the desktop is unreachable and the
 * ANZU voice packs (Whisper / Pocket TTS, RFC-0140) are not installed. Recognition prefers the
 * on-device recognizer so it keeps working in airplane mode when the phone has the language pack.
 * All recognizer calls must happen on the main thread.
 */
class PlatformVoice(
    private val context: Context,
    /** RFC-0216 S4 voice-language setting: the single language source for TTS and STT. */
    private val language: () -> VoiceLanguageSetting = { VoiceLanguageSetting() },
    private val sttLanguage: SttLanguageSource = SttLanguageSource.fromVoiceLanguage(language),
    /** Called on the main thread once the TextToSpeech engine finished starting (or failed). */
    private val onTtsReady: (Boolean) -> Unit = {},
) {
    private var recognizer: SpeechRecognizer? = null
    @Volatile var ttsReady: Boolean = false
        private set
    private var tts: TextToSpeech? = null
    @Volatile var listening: Boolean = false
        private set
    @Volatile var speaking: Boolean = false
        private set
    @Volatile private var stopRequested: Boolean = false
    /** Bumped on every startListening/cancel so a previous session's late callbacks are ignored. */
    private var session: Int = 0
    private val handler = Handler(Looper.getMainLooper())
    private val timers = mutableListOf<Runnable>()
    private var requestStop: (() -> Unit)? = null

    init {
        tts = TextToSpeech(context.applicationContext) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (!ttsReady) Log.w(TAG, "Built-in text-to-speech failed to start (status $status)")
            onTtsReady(ttsReady)
        }
    }

    fun sttAvailable(): Boolean = recognizerCandidates().isNotEmpty()

    private fun onDeviceRecognizerAvailable(): Boolean =
        Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(context)

    @Suppress("DEPRECATION")
    private fun externalRecognizer(): android.content.ComponentName? = context.packageManager
        .queryIntentServices(Intent(android.speech.RecognitionService.SERVICE_INTERFACE), 0)
        .firstOrNull { it.serviceInfo.packageName != context.packageName }?.serviceInfo?.let {
            android.content.ComponentName(it.packageName, it.name)
        }

    private fun recognizerCandidates(): List<PlatformRecognizerKind> = PlatformSttPlan.candidates(
        onDeviceAvailable = onDeviceRecognizerAvailable(),
        defaultAvailable = externalRecognizer() != null,
    )

    fun startListening(onPartial: (String) -> Unit, onResult: (String) -> Unit, onError: (String) -> Unit, onCaptureEnd: () -> Unit = {}, onUnavailable: ((String) -> Unit)? = null) {
        // Cancel + destroy any previous recognizer first: its late onResults/onError must not reach this session.
        cancelListening()
        stopRequested = false
        val current = session
        val languageTag = sttLanguage.languageTag()
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            onError(errorCopy(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS, languageTag))
            return
        }
        val candidates = recognizerCandidates()
        if (candidates.isEmpty()) {
            (onUnavailable ?: onError)(PlatformSttPlan.NO_RECOGNIZER_COPY)
            return
        }
        listening = true
        attempt(current, languageTag, candidates, 0, onPartial, onResult, onError, onCaptureEnd, onUnavailable)
    }

    private fun attempt(
        current: Int,
        languageTag: String,
        candidates: List<PlatformRecognizerKind>,
        index: Int,
        onPartial: (String) -> Unit,
        onResult: (String) -> Unit,
        onError: (String) -> Unit,
        onCaptureEnd: () -> Unit,
        onUnavailable: ((String) -> Unit)?,
    ) {
        val kind = candidates[index]
        val next = when (kind) {
            // ON_DEVICE is only a candidate on API 31+ (onDeviceRecognizerAvailable); explicit guard for lint NewApi.
            PlatformRecognizerKind.ON_DEVICE -> if (Build.VERSION.SDK_INT >= 31) SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
                else SpeechRecognizer.createSpeechRecognizer(context)
            PlatformRecognizerKind.DEFAULT -> SpeechRecognizer.createSpeechRecognizer(context, externalRecognizer())
        }
        var heardSpeech = false
        var partial = ""
        var quietSince = 0L
        fun stale() = current != session || recognizer !== next
        fun later(ms: Long, block: () -> Unit) {
            val task = Runnable { if (!stale()) block() }
            timers += task
            handler.postDelayed(task, ms)
        }
        fun finish(text: String?) {
            if (stale()) return
            listening = false
            release()
            if (text.isNullOrBlank()) onError(errorCopy(SpeechRecognizer.ERROR_NO_MATCH, languageTag)) else onResult(text)
        }
        fun endpoint() {
            if (stale() || stopRequested) return
            stopRequested = true
            listening = false
            onCaptureEnd()
            next.stopListening()
            later(VoiceEndpoint.FINAL_RESULT_MS) { finish(partial) }
        }
        requestStop = ::endpoint
        next.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() { if (!stale()) { heardSpeech = true; quietSince = 0L } }
            override fun onRmsChanged(rmsdB: Float) {
                if (stale() || !heardSpeech || stopRequested) return
                if (rmsdB > 1.5f) quietSince = 0L
                else if (quietSince == 0L) {
                    quietSince = android.os.SystemClock.elapsedRealtime()
                    val started = quietSince
                    later(VoiceEndpoint.SILENCE_MS) { if (quietSince == started) endpoint() }
                }
            }
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() { endpoint() }
            override fun onEvent(eventType: Int, params: Bundle?) {}
            override fun onPartialResults(partialResults: Bundle?) {
                if (stale()) return
                bestResult(partialResults)?.let { partial = it; heardSpeech = true; onPartial(it) }
            }
            override fun onResults(results: Bundle?) {
                if (stale()) return
                finish(bestResult(results) ?: partial)
            }
            override fun onError(error: Int) {
                if (stale()) {
                    Log.w(TAG, "Ignoring late speech recognition error $error from a previous session")
                    return
                }
                if (partial.isNotBlank()) { finish(partial); return }
                release()
                Log.w(TAG, "Built-in speech recognition error $error from $kind recognizer")
                if (listening && !stopRequested && PlatformSttPlan.shouldFallBack(error, heardSpeech, hasNext = index + 1 < candidates.size)) {
                    attempt(current, languageTag, candidates, index + 1, onPartial, onResult, onError, onCaptureEnd, onUnavailable)
                    return
                }
                listening = false
                val unavailable = !stopRequested && PlatformSttPlan.shouldFallBack(error, heardSpeech, hasNext = true)
                (if (unavailable) onUnavailable ?: onError else onError)(errorCopy(error, languageTag))
            }
        })
        recognizer = next
        try {
            next.startListening(recognizerIntent(languageTag))
            later(VoiceEndpoint.NO_SPEECH_MS) { if (!heardSpeech) finish(null) }
            later(VoiceEndpoint.MAX_CAPTURE_MS) { endpoint() }
        } catch (exc: Exception) {
            listening = false
            release()
            onError(exc.message ?: "Speech recognition could not start")
        }
    }

    /** Ends capture; the recognizer then delivers its final result through the listener. */
    fun stopListening() {
        requestStop?.invoke()
    }

    fun cancelListening() {
        session++
        listening = false
        recognizer?.cancel()
        release()
    }

    /** Installed voices for the given ANZU voice language, best first (RFC-0216 S4). */
    fun voicesFor(setting: VoiceLanguageSetting = language()): List<TtsVoiceCandidate> {
        val engine = tts ?: return emptyList()
        if (!ttsReady) return emptyList()
        return VoiceLanguagePrefs.rankVoices(candidates(engine), setting)
    }

    /** True when this phone can speak [setting]'s language without falling back to another locale. */
    fun supportsLanguage(setting: VoiceLanguageSetting = language()): Boolean = voicesFor(setting).isNotEmpty()

    private fun candidates(engine: TextToSpeech): List<TtsVoiceCandidate> = try {
        engine.voices.orEmpty().map { v ->
            TtsVoiceCandidate(v.name, v.locale, v.quality, v.latency, v.isNetworkConnectionRequired,
                v.features?.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) == true)
        }
    } catch (e: RuntimeException) {
        Log.w(TAG, "Could not list text-to-speech voices", e)
        emptyList()
    }

    /** Applies ANZU's voice language/voice, never the raw system locale. Returns an error message or null. */
    private fun applyLanguage(engine: TextToSpeech): String? {
        val setting = language()
        val pick = VoiceLanguagePrefs.pickVoice(candidates(engine), setting)
            ?: return VoiceLanguagePrefs.missingVoiceMessage(setting)
        val voice: Voice? = engine.voices.orEmpty().firstOrNull { it.name == pick.name }
        if (voice == null || engine.setVoice(voice) != TextToSpeech.SUCCESS) {
            return VoiceLanguagePrefs.missingVoiceMessage(setting)
        }
        return null
    }

    fun speak(text: String, onDone: () -> Unit, onError: (String) -> Unit) {
        val engine = tts
        if (engine == null || !ttsReady) {
            onError("This phone's text-to-speech is not ready")
            return
        }
        applyLanguage(engine)?.let { onError(it); return }
        val id = UUID.randomUUID().toString()
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) { speaking = true }
            override fun onDone(utteranceId: String?) { if (utteranceId == id) { speaking = false; onDone() } }
            override fun onStop(utteranceId: String?, interrupted: Boolean) { speaking = false; onDone() }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                speaking = false
                Log.w(TAG, "Built-in text-to-speech failed for an utterance")
                onError("This phone's text-to-speech failed")
            }
        })
        val chunks = SpeakableTtsChunker.chunk(text)
        if (chunks.isEmpty()) {
            onError("Nothing speakable in that reply")
            return
        }
        speaking = true
        chunks.forEachIndexed { index, piece ->
            engine.speak(piece, if (index == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD, null,
                if (index == chunks.lastIndex) id else "$id-$index")
        }
    }

    fun stopSpeaking() {
        speaking = false
        tts?.stop()
    }

    fun shutdown() {
        cancelListening()
        tts?.stop()
        tts?.shutdown()
        tts = null
        ttsReady = false
    }

    private fun release() {
        timers.forEach(handler::removeCallbacks)
        timers.clear()
        requestStop = null
        recognizer?.destroy()
        recognizer = null
    }

    private fun bestResult(bundle: Bundle?): String? =
        bundle?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim()?.takeIf { it.isNotEmpty() }

    private fun recognizerIntent(languageTag: String): Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
        .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, VoiceEndpoint.SILENCE_MS)
        .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, VoiceEndpoint.SILENCE_MS)

    companion object {
        fun languageDisplayName(languageTag: String): String =
            Locale.forLanguageTag(languageTag).getDisplayName(Locale.ENGLISH).ifBlank { languageTag }

        fun errorCopy(code: Int, languageTag: String): String = when (code) {
            SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "I didn't catch that. Tap the mic and try again."
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
                "Microphone permission is required to talk to ANZU. Allow it in Settings → Apps → ANZU → Permissions → Microphone."
            SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT, SpeechRecognizer.ERROR_SERVER ->
                "This phone has no offline speech pack for your language. Install one in Android settings (Speech recognition → offline languages) or download ANZU's voice pack in More → Voice."
            SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED, SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE ->
                "This phone's speech recognizer has no ${languageDisplayName(languageTag)} language pack. Download it in Android settings (Google → Speech recognition → offline languages) or download ANZU's voice pack in More → Voice."
            SpeechRecognizer.ERROR_SERVER_DISCONNECTED, SpeechRecognizer.ERROR_CANNOT_CHECK_SUPPORT ->
                "This phone's speech service stopped responding. Make sure Speech Recognition and Synthesis from Google is installed and enabled, or download ANZU's voice pack in More → Voice."
            SpeechRecognizer.ERROR_TOO_MANY_REQUESTS -> "Speech recognition is rate-limited right now. Try again in a moment."
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Speech recognition is busy. Try again in a moment."
            SpeechRecognizer.ERROR_AUDIO -> "The microphone is unavailable. Another app or a call may be using it."
            else -> "Speech recognition failed on this phone (code $code)."
        }
    }
}

/**
 * The speech-recognition language (BCP-47 tag) handed to Android recognizers. The system locale (e.g. nl-NL)
 * must not pick it. RFC-0216 S4: it is always derived from the voice-language setting (one source), resolved
 * to a regioned tag because recognizers reject bare tags (`en` → `en-US`).
 */
fun interface SttLanguageSource {
    fun languageTag(): String

    companion object {
        fun fromVoiceLanguage(setting: () -> VoiceLanguageSetting) = SttLanguageSource { setting().recognizerLanguage }
    }
}

enum class PlatformRecognizerKind { ON_DEVICE, DEFAULT }

/**
 * Which Android recognizer to try, in order, and when a failure means "try the next one" (RFC-0216 S3).
 *
 * Samsung phones report an on-device recognition service, but it often lacks the requested language pack
 * and answers ERROR_LANGUAGE_NOT_SUPPORTED / ERROR_LANGUAGE_UNAVAILABLE (or drops the binding) before any
 * audio is captured. That must fall through to the phone's default recognizer instead of ending the listen.
 */
object PlatformSttPlan {
    const val NO_RECOGNIZER_COPY =
        "This phone has no speech recognizer ANZU can use. Install or enable Speech Recognition and Synthesis from Google, or download ANZU's voice pack in More → Voice."

    private val FALLBACK_ERRORS = setOf(
        SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED,
        SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE,
        SpeechRecognizer.ERROR_CANNOT_CHECK_SUPPORT,
        SpeechRecognizer.ERROR_SERVER_DISCONNECTED,
        SpeechRecognizer.ERROR_CLIENT,
    )

    fun candidates(onDeviceAvailable: Boolean, defaultAvailable: Boolean): List<PlatformRecognizerKind> = buildList {
        if (onDeviceAvailable) add(PlatformRecognizerKind.ON_DEVICE)
        if (defaultAvailable) add(PlatformRecognizerKind.DEFAULT)
    }

    /** Fall back only for recognizer/binding failures that happened before the owner started speaking. */
    fun shouldFallBack(error: Int, heardSpeech: Boolean, hasNext: Boolean): Boolean =
        hasNext && !heardSpeech && error in FALLBACK_ERRORS
}
