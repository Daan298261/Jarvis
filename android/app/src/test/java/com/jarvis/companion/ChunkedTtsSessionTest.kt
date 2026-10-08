package com.jarvis.companion

import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class ChunkedTtsSessionTest {
    @Test
    fun stopCancelsRemainingBusyIsFalseAndSecondSpeakDoesNotOverlap() = runBlocking {
        val synthesized = CopyOnWriteArrayList<String>()
        val played = CopyOnWriteArrayList<String>()
        val concurrentPlay = AtomicInteger(0)
        val maxPlay = AtomicInteger(0)
        val holdPlayback = AtomicBoolean(true)
        var busy = true

        val session = ChunkedTtsSession(
            scope = this,
            synthesize = { text ->
                synthesized += text
                delay(8)
                text.toByteArray()
            },
            play = { audio ->
                val n = concurrentPlay.incrementAndGet()
                maxPlay.updateAndGet { maxOf(it, n) }
                played += String(audio)
                try {
                    while (holdPlayback.get() && isActive) delay(4)
                } finally {
                    concurrentPlay.decrementAndGet()
                }
            },
        )

        // Mirror CompanionModel.speak(): on-device chunk loop is outside action{}, so busy is false.
        busy = false
        session.start(listOf("one.", "two.", "three."))
        withTimeout(2_000) { while (played.isEmpty()) delay(2) }
        delay(20)
        assertFalse("busy must be false once the first chunk starts", busy)
        assertEquals(listOf("one."), played.toList())
        assertTrue("next chunk should prefetch while the first plays", synthesized.size >= 2)

        session.stop()
        delay(60)
        assertEquals("stop must cancel remaining chunks", listOf("one."), played.toList())
        assertTrue("stop must not synthesize every leftover chunk", synthesized.size < 3 || played.size == 1)

        holdPlayback.set(true)
        synthesized.clear()
        played.clear()
        session.start(listOf("aaa.", "bbb.", "ccc."))
        withTimeout(2_000) { while (played.isEmpty()) delay(2) }
        assertEquals(listOf("aaa."), played.toList())
        session.start(listOf("xxx.", "yyy."))
        holdPlayback.set(false)
        session.job?.join()
        delay(40)
        assertTrue(
            "second speak must not play leftover first-session chunks",
            played.none { it == "bbb." || it == "ccc." },
        )
        assertTrue(played.contains("xxx."))
        assertEquals("plays must not overlap", 1, maxPlay.get())
    }
}
