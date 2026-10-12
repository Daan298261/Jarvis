package com.jarvis.companion

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import kotlin.random.Random

class TransientRetryTest {
    @Test
    fun jitterStaysWithinExponentialCeiling() {
        val random = Random(7)
        repeat(200) {
            assertTrue(TransientRetry.delayMs(1, random) in 0..400)
            assertTrue(TransientRetry.delayMs(3, random) in 0..1600)
            assertTrue(TransientRetry.delayMs(12, random) in 0..TransientRetry.MAX_DELAY_MS)
        }
    }

    @Test
    fun retriesTransportErrorsThenSucceeds() = runBlocking {
        var calls = 0
        val sleeps = mutableListOf<Long>()
        val value = TransientRetry.run(sleep = { sleeps += it }) {
            calls++
            if (calls < 3) throw java.io.IOException("wifi handoff")
            "ok"
        }
        assertEquals("ok", value)
        assertEquals(3, calls)
        assertEquals(2, sleeps.size)
    }

    @Test
    fun serverAnswersAreNotRetried() = runBlocking {
        var calls = 0
        try {
            TransientRetry.run(sleep = {}) {
                calls++
                throw ApiException(401, "Pairing code expired or invalid")
            }
            fail("expected ApiException")
        } catch (error: ApiException) {
            assertEquals(401, error.status)
        }
        assertEquals(1, calls)
    }

    @Test
    fun givesUpAfterAttemptsWithLastError() = runBlocking {
        var calls = 0
        try {
            TransientRetry.run(attempts = 2, sleep = {}) {
                calls++
                throw java.io.IOException("down $calls")
            }
            fail("expected IOException")
        } catch (error: java.io.IOException) {
            assertEquals("down 2", error.message)
        }
        assertEquals(2, calls)
    }
}
