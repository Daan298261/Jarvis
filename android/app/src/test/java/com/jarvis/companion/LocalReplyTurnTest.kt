package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * RFC-0235 streaming lifecycle (D2 on #671): cancel, error, memory-pressure warning and stall,
 * through the real [LocalReplyTurn], [withOfflineAnswerCleanup] and [CompanionPackManager.generate]
 * with a fake engine.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33], shadows = [ReplaceAtomicFileShadow::class])
class LocalReplyTurnTest {
    private lateinit var context: Context
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val user = JSONObject().put("id", "u1").put("role", "user").put("content", "hello")
    private val prior = listOf(user)

    @Before fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("companion_pack", Context.MODE_PRIVATE).edit().clear().apply()
        context.getSharedPreferences("companion_pack_digest", Context.MODE_PRIVATE).edit().clear().apply()
    }

    @After fun tearDown() { scope.cancel() }

    /** Streams [partial], then blocks in "native decode" until asked to stop, like a hung llama.cpp pass. */
    private class HangingEngine(private val partial: String) : ScriptedInferenceEngine(partial) {
        @Volatile var cancelRequests = 0
        override fun requestCancel() { cancelRequests++; cancelled = true }
        override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
            if (partial.isNotEmpty()) onToken(partial)
            val until = System.currentTimeMillis() + 10_000
            while (!cancelled && System.currentTimeMillis() < until) Thread.sleep(5)
            return GenerateOutcome(cancelled = true)
        }
    }

    private fun manager(engine: LocalInferenceEngine, deadlines: LocalStallDeadlines = LocalStallDeadlines()): CompanionPackManager {
        val manager = CompanionPackManager(context, engine, stallDeadlines = deadlines)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        manager.packFile(pack).apply { parentFile?.mkdirs(); writeBytes("gguf-fixture".toByteArray()) }
        return manager
    }

    private fun state() = MutableStateFlow(CompanionState(messages = prior))

    private suspend fun answer(turn: LocalReplyTurn, manager: CompanionPackManager): Result<String> =
        turn.answer(scope, manager, clearPicked = {}, keepWarm = { false }, onStart = {}, onFinally = {}) {
            manager.generate("hello", 64, onProgress = turn.progress) { turn.reply.append(it) }
            turn.reply.text()
        }

    @Test fun cancelledStreamLeavesNoPartialReplyInChatOrOnHome() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = HangingEngine("Half of an answer")
        val manager = manager(engine)
        val job = scope.launch { answer(turn, manager) }
        withTimeout(5_000) { while (state.value.liveLocalReply.isEmpty()) kotlinx.coroutines.delay(5) }
        assertEquals("Half of an answer", state.value.liveLocalReply)
        assertEquals(2, state.value.messages.size)
        job.cancelAndJoin()
        assertEquals("", state.value.liveLocalReply)
        assertEquals(prior, state.value.messages)
        assertTrue("native decode was asked to stop", engine.cancelRequests >= 1)
        assertEquals(null, state.value.error)
    }

    @Test fun failedStreamShowsTheErrorAsAnErrorNotAsAReply() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = object : ScriptedInferenceEngine("Partial") {
            override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
                onToken("Partial reply before the crash")
                return GenerateOutcome(error = "boom mid-answer")
            }
        }
        val result = answer(turn, manager(engine))
        assertTrue(result.isFailure)
        assertEquals("boom mid-answer", state.value.error)
        assertEquals("", state.value.liveLocalReply)
        assertEquals("the partial and the error are not chat replies", prior, state.value.messages)
    }

    @Test fun landedReplyClearsTheHomePreviewAndStaysInChat() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val result = answer(turn, manager(ScriptedInferenceEngine("A full reply.")))
        val saved = StandaloneActions.chatMessage("a1", "assistant", result.getOrThrow(), StandaloneActions.ORIGIN_ASSISTANT)
        turn.landed(saved)
        assertEquals("", state.value.liveLocalReply)
        assertEquals(2, state.value.messages.size)
        assertEquals("A full reply.", state.value.messages.last().optString("text"))
    }

    @Test fun stageTickerKeepsTheMemoryPressureWarningVisible() {
        var now = 1_000L
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1") { now }
        turn.pressure("Phone memory is low: answers are shorter")
        assertEquals("Phone memory is low: answers are shorter", state.value.activity)
        turn.progress("Writing reply")
        now += 3_000
        turn.tick()
        assertEquals("Phone memory is low: answers are shorter · Writing reply · 3s", state.value.activity)
        now += 1_000
        turn.tick()
        assertTrue(state.value.activity.startsWith("Phone memory is low: answers are shorter"))
    }

    @Test fun stageTickerWithoutPressureShowsStageAndElapsed() {
        var now = 0L
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1") { now }
        turn.progress("Loading model on this phone")
        now = 2_400
        turn.tick()
        assertEquals("Loading model on this phone · 2s", state.value.activity)
    }

    @Test fun idleStallRaisesTypedErrorStopsDecodeAndReleasesTheSendLock() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = HangingEngine("Started then went quiet")
        val manager = manager(engine, LocalStallDeadlines(firstTokenMs = 5_000, idleMs = 200))
        val sendLock = Mutex()
        val started = System.currentTimeMillis()
        val result = sendLock.withLock { answer(turn, manager) }
        val stall = result.exceptionOrNull() as LocalStreamStallError
        assertEquals(LocalStreamStallError.IDLE, stall.deadline)
        assertEquals(200, stall.budgetMs)
        assertTrue(System.currentTimeMillis() - started < 4_000)
        assertTrue("native decode was asked to stop", engine.cancelRequests >= 1)
        assertFalse("the send lock is released", sendLock.isLocked)
        assertTrue(state.value.error!!.contains("stalled (idle)"))
        assertEquals("", state.value.liveLocalReply)
        assertEquals(prior, state.value.messages)
    }

    @Test fun firstTokenStallRaisesTypedError() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = HangingEngine("")
        val manager = manager(engine, LocalStallDeadlines(firstTokenMs = 250, idleMs = 5_000))
        val stall = answer(turn, manager).exceptionOrNull() as LocalStreamStallError
        assertEquals(LocalStreamStallError.FIRST_TOKEN, stall.deadline)
        assertTrue(stall.elapsedMs >= 250)
        assertTrue(engine.cancelRequests >= 1)
        assertTrue(state.value.error!!.contains("stalled (first_token)"))
    }

    @Test fun steadyStreamUnderTheDeadlinesIsNotAStall() = runBlocking {
        val engine = object : ScriptedInferenceEngine("") {
            override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
                repeat(8) { onToken("tok$it "); Thread.sleep(60) }
                return GenerateOutcome()
            }
        }
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val result = answer(turn, manager(engine, LocalStallDeadlines(firstTokenMs = 300, idleMs = 200)))
        assertTrue(result.getOrThrow().startsWith("tok0"))
        assertEquals(null, state.value.error)
    }
}
