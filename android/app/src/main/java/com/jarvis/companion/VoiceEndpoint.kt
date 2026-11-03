package com.jarvis.companion

import kotlin.math.sqrt

/** Monotonic audio-time endpoint. Initial quiet is not mistaken for a finished sentence. */
class VoiceEndpoint {
    private var elapsed = 0L
    private var quiet = 0L
    private var speech = 0L
    val heardSpeech: Boolean get() = speech >= 80
    fun accept(pcm: ByteArray, size: Int = pcm.size): Boolean {
        val samples = size / 2
        if (samples == 0) return false
        var energy = 0.0
        for (i in 0 until samples) {
            val value = ((pcm[i * 2].toInt() and 255) or (pcm[i * 2 + 1].toInt() shl 8)).toShort().toDouble()
            energy += value * value
        }
        val duration = samples * 1000L / 16000
        elapsed += duration
        if (sqrt(energy / samples) >= 420) { speech += duration; quiet = 0 } else quiet += duration
        return (speech >= 80 && quiet >= SILENCE_MS) || (speech == 0L && elapsed >= NO_SPEECH_MS) || elapsed >= MAX_CAPTURE_MS
    }
    companion object {
        const val SILENCE_MS = 250L
        const val NO_SPEECH_MS = 5000L
        const val MAX_CAPTURE_MS = 60000L
        const val FINAL_RESULT_MS = 1200L
    }
}
