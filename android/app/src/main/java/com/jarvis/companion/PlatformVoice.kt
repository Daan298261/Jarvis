package com.jarvis.companion

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import java.util.Locale
import java.util.UUID

private const val TAG = "PlatformVoice"

/**
 * Android's built-in SpeechRecognizer and TextToSpeech, used when the desktop is unreachable and the
 * ANZU voice packs (Whisper / Pocket TTS, RFC-0140) are not installed. Recognition prefers the
 * on-device recognizer so it keeps working in airplane mode when the phone has the language pack.
 * All recognizer calls must happen on the main thread.
 */
class PlatformVoice(private val context: Context) {
    private var recognizer: SpeechRecognizer? = null
    @Volatile var ttsReady: Boolean = false
        private set
    private var tts: TextToSpeech? = null
    @Volatile var listening: Boolean = false
        private set
    @Volatile var speaking: Boolean = false
        private set

    init {
        tts = TextToSpeech(context.applicationContext) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (!ttsReady) Log.w(TAG, "Built-in text-to-speech failed to start (status $status)")
        }
    }

    fun sttAvailable(): Boolean = onDeviceRecognizerAvailable() || SpeechRecognizer.isRecognitionAvailable(context)

    private fun onDeviceRecognizerAvailable(): Boolean =
        Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(context)

    fun startListening(onPartial: (String) -> Unit, onResult: (String) -> Unit, onError: (String) -> Unit) {
        stopListening()
        val next = if (onDeviceRecognizerAvailable()) SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        else SpeechRecognizer.createSpeechRecognizer(context)
        next.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
            override fun onPartialResults(partialResults: Bundle?) {
                bestResult(partialResults)?.let(onPartial)
            }
            override fun onResults(results: Bundle?) {
                listening = false
                release()
                val text = bestResult(results)
                if (text.isNullOrBlank()) onError(errorCopy(SpeechRecognizer.ERROR_NO_MATCH)) else onResult(text)
            }
            override fun onError(error: Int) {
                listening = false
                release()
                Log.w(TAG, "Built-in speech recognition error $error")
                onError(errorCopy(error))
            }
        })
        recognizer = next
        listening = true
        next.startListening(recognizerIntent())
    }

    /** Ends capture; the recognizer then delivers its final result through the listener. */
    fun stopListening() {
        recognizer?.stopListening()
    }

    fun cancelListening() {
        listening = false
        recognizer?.cancel()
        release()
    }

    fun speak(text: String, onDone: () -> Unit, onError: (String) -> Unit) {
        val engine = tts
        if (engine == null || !ttsReady) {
            onError("This phone's text-to-speech is not ready")
            return
        }
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
        recognizer?.destroy()
        recognizer = null
    }

    private fun bestResult(bundle: Bundle?): String? =
        bundle?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim()?.takeIf { it.isNotEmpty() }

    private fun recognizerIntent(): Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
        .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)

    companion object {
        fun errorCopy(code: Int): String = when (code) {
            SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "I didn't catch that. Tap the mic and try again."
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is required to talk to ANZU."
            SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT, SpeechRecognizer.ERROR_SERVER ->
                "This phone has no offline speech pack for your language. Install one in Android settings (Speech recognition → offline languages) or download ANZU's voice pack in More → Voice."
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Speech recognition is busy. Try again in a moment."
            SpeechRecognizer.ERROR_AUDIO -> "The microphone is unavailable."
            else -> "Speech recognition failed on this phone (code $code)."
        }
    }
}
