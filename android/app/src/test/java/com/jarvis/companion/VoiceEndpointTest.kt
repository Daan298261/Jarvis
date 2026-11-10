package com.jarvis.companion

import org.junit.Assert.*
import org.junit.Test

class VoiceEndpointTest {
    private fun frame(value: Int, ms: Int = 10): ByteArray = ByteArray(ms * 32).also { bytes ->
        for (i in bytes.indices step 2) { bytes[i] = value.toByte(); bytes[i + 1] = (value shr 8).toByte() }
    }
    @Test fun endsAt250MillisecondsAfterSpeech() {
        val endpoint = VoiceEndpoint()
        repeat(10) { assertFalse(endpoint.accept(frame(1600))) }
        repeat(24) { assertFalse(endpoint.accept(frame(0))) }
        assertTrue(endpoint.accept(frame(0)))
    }
    @Test fun resumedSpeechResetsSilence() {
        val endpoint = VoiceEndpoint()
        repeat(10) { endpoint.accept(frame(1600)) }
        repeat(20) { assertFalse(endpoint.accept(frame(0))) }
        assertFalse(endpoint.accept(frame(1600)))
        repeat(24) { assertFalse(endpoint.accept(frame(0))) }
        assertTrue(endpoint.accept(frame(0)))
    }
    @Test fun initialSilenceHasBoundedGracePeriod() {
        val endpoint = VoiceEndpoint()
        repeat(499) { assertFalse(endpoint.accept(frame(0))) }
        assertTrue(endpoint.accept(frame(0)))
    }
    @Test fun continuousInputHasMaximumDuration() {
        val endpoint = VoiceEndpoint()
        repeat(5999) { assertFalse(endpoint.accept(frame(-1600))) }
        assertTrue(endpoint.accept(frame(-1600)))
    }
}
