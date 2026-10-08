package com.jarvis.companion

import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
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

        session.start(listOf("one.", "two.", "three."))
        withTimeout(2_000) { while (played.isEmpty()) delay(2) }
        delay(20)
        assertTrue("session must be running while a chunk is held for playback", session.isRunning())
        assertEquals(listOf("one."), played.toList())
        assertTrue("next chunk should prefetch while the first plays", synthesized.size >= 2)

        session.stop()
        session.job?.join()
        delay(20)
        assertFalse("stop must leave the session idle", session.isRunning())
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
        assertFalse(session.isRunning())
    }

    @Test
    fun throwingSynthCallsOnErrorAndDoesNotHitExceptionHandler() = runBlocking {
        val handlerHits = CopyOnWriteArrayList<Throwable>()
        val handler = CoroutineExceptionHandler { _, t -> handlerHits += t }
        val supervisor = SupervisorJob()
        val scope = CoroutineScope(coroutineContext + supervisor + handler)
        val errors = CopyOnWriteArrayList<Throwable>()
        val session = ChunkedTtsSession(
            scope = scope,
            synthesize = { error("near-silent refusal") },
            play = {},
            onError = { errors += it },
        )
        session.start(listOf("hello there.")).join()
        assertEquals(1, errors.size)
        assertTrue(errors[0].message!!.contains("near-silent refusal"))
        assertTrue("CoroutineExceptionHandler must stay silent", handlerHits.isEmpty())
        supervisor.cancel()
    }

    @Test
    fun stopRunsOnIdleCleanupExactlyOnce() = runBlocking {
        val idle = AtomicInteger(0)
        val holdPlayback = AtomicBoolean(true)
        val session = ChunkedTtsSession(
            scope = this,
            synthesize = { it.toByteArray() },
            play = {
                while (holdPlayback.get() && isActive) delay(4)
            },
            onIdle = { idle.incrementAndGet() },
        )
        session.start(listOf("one.", "two."))
        withTimeout(2_000) { while (!session.isRunning()) delay(2) }
        delay(20)
        session.stop()
        session.job?.join()
        delay(20)
        assertEquals(1, idle.get())
        assertFalse(session.isRunning())
        session.stop()
        delay(20)
        assertEquals("a second stop must not rerun cleanup", 1, idle.get())
    }
}
