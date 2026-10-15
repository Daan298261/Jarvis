package com.jarvis.companion

import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.SpeechRecognizer

/** Required assistant metadata endpoint. Delegates to an installed recognizer, never to itself. */
class AnzuRecognitionService : RecognitionService() {
    private var recognizer: SpeechRecognizer? = null
    override fun onStartListening(recognizerIntent: Intent, listener: Callback) {
        release()
        @Suppress("DEPRECATION")
        val service = packageManager.queryIntentServices(Intent(SERVICE_INTERFACE), 0)
            .firstOrNull { it.serviceInfo.packageName != packageName }?.serviceInfo
        if (service == null) { listener.error(SpeechRecognizer.ERROR_CLIENT); return }
        try {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this, ComponentName(service.packageName, service.name)).also { delegate ->
                delegate.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) { listener.readyForSpeech(params) }
                    override fun onBeginningOfSpeech() { listener.beginningOfSpeech() }
                    override fun onRmsChanged(rmsdB: Float) { listener.rmsChanged(rmsdB) }
                    override fun onBufferReceived(buffer: ByteArray?) { listener.bufferReceived(buffer) }
                    override fun onEndOfSpeech() { listener.endOfSpeech() }
                    override fun onError(error: Int) { listener.error(error); release() }
                    override fun onResults(results: Bundle?) { listener.results(results); release() }
                    override fun onPartialResults(partialResults: Bundle?) { listener.partialResults(partialResults) }
                    override fun onEvent(eventType: Int, params: Bundle?) { }
                })
                delegate.startListening(recognizerIntent)
            }
        } catch (_: Exception) { release(); listener.error(SpeechRecognizer.ERROR_CLIENT) }
    }
    override fun onStopListening(listener: Callback) { recognizer?.stopListening() }
    override fun onCancel(listener: Callback) { release() }
    override fun onDestroy() { release(); super.onDestroy() }
    private fun release() { val old = recognizer; recognizer = null; old?.destroy() }
}
