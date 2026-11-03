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

    @Test fun failedStreamDropsThePartialAndKeepsTheErrorBubble() = runBlocking {
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
        // The partial is gone; the error keeps its unsaved error bubble in Chat (live UI is add-only).
        assertEquals(prior.size + 1, state.value.messages.size)
        assertEquals(prior, state.value.messages.take(prior.size))
        assertEquals("boom mid-answer", state.value.messages.last().optString("text"))
        assertEquals("assistant", state.value.messages.last().optString("role"))
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

    @Test fun idleStallRaisesTypedErrorAndStopsDecode() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = HangingEngine("Started then went quiet")
        val manager = manager(engine, LocalStallDeadlines(firstTokenMs = 5_000, idleMs = 200))
        val started = System.currentTimeMillis()
        val result = answer(turn, manager)
        val stall = result.exceptionOrNull() as LocalStreamStallError
        assertEquals(LocalStreamStallError.IDLE, stall.deadline)
        assertEquals(200, stall.budgetMs)
        assertTrue(System.currentTimeMillis() - started < 4_000)
        assertTrue("native decode was asked to stop", engine.cancelRequests >= 1)
        assertTrue(state.value.error!!.contains("stalled (idle)"))
        assertEquals("", state.value.liveLocalReply)
        assertEquals(prior.size + 1, state.value.messages.size)
        assertEquals(state.value.error, state.value.messages.last().optString("text"))
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

    // ---- RFC-0235 tests the spec lists (A, C, D) --------------------------------------------------

    @Test fun failedTurnKeepsItsErrorBubbleAndClearsOnlyThePartialAndHomePreview() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = object : ScriptedInferenceEngine("") {
            override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
                onToken("Partial reply before the crash")
                return GenerateOutcome(error = "boom mid-answer")
            }
        }
        assertTrue(answer(turn, manager(engine)).isFailure)
        val messages = state.value.messages
        assertEquals("prior plus exactly one error bubble", prior.size + 1, messages.size)
        assertEquals("boom mid-answer", messages.last().optString("text"))
        assertEquals("assistant", messages.last().optString("role"))
        assertTrue("the partial reply is in no message", messages.none { it.optString("text").contains("Partial reply") })
        assertEquals("", state.value.liveLocalReply)
        assertEquals("boom mid-answer", state.value.error)
    }

    @Test fun defaultStallDeadlinesAre120s30s180sAnd300s() {
        val defaults = LocalStallDeadlines()
        assertEquals(120_000, defaults.firstTokenMs)
        assertEquals(30_000, defaults.idleMs)
        assertEquals("the load phase", 180_000, defaults.loadMs)
        assertEquals("the whole call", 300_000, defaults.turnMs)
    }

    @Test fun nonPositiveStallDeadlineIsRejected() {
        listOf(
            { LocalStallDeadlines(firstTokenMs = 0) }, { LocalStallDeadlines(idleMs = -1) },
            { LocalStallDeadlines(loadMs = 0) }, { LocalStallDeadlines(turnMs = -5) },
        ).forEach { build ->
            val rejected = runCatching { build() }.exceptionOrNull()
            assertTrue(rejected is IllegalArgumentException)
        }
    }

    /** Over-budget picked text, so the planner splits it into sections that are summarised first. */
    private class SectionedEngine(private val onGenerate: (String, (String) -> Unit, SectionedEngine) -> GenerateOutcome) : ScriptedInferenceEngine("") {
        val prompts = java.util.concurrent.CopyOnWriteArrayList<String>()
        @Volatile var cancelRequests = 0
        override fun requestCancel() { cancelRequests++; cancelled = true }
        override fun tokenize(text: String): Int = if (text.contains("PICKED-BLOCK")) 8000 else (text.length + 3) / 4
        override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
            cancelled = false
            prompts.add(prompt)
            return onGenerate(prompt, onToken, this)
        }
    }

    private suspend fun generateSectioned(manager: CompanionPackManager) {
        val picked = "PICKED-BLOCK " + "word ".repeat(400)
        manager.generate(
            prompt = StandalonePrompt.build(emptyList(), "Summarize this file", picked), maxTokens = 256,
            history = emptyList(), latest = "Summarize this file", pickedText = picked, onToken = {},
        )
    }

    @Test fun sectionSummaryPassStallRaisesTypedError() = runBlocking {
        val engine = SectionedEngine { _, _, e ->
            val until = System.currentTimeMillis() + 10_000
            while (!e.cancelled && System.currentTimeMillis() < until) Thread.sleep(5)
            GenerateOutcome(cancelled = true)
        }
        val manager = manager(engine, LocalStallDeadlines(firstTokenMs = 250, idleMs = 5_000))
        val stall = runCatching { generateSectioned(manager) }.exceptionOrNull() as LocalStreamStallError
        assertEquals(LocalStreamStallError.FIRST_TOKEN, stall.deadline)
        assertEquals("the stalled pass is a section summary, not the reply", 1, engine.prompts.size)
        assertTrue(engine.prompts.single().contains("Summarize this section"))
        assertTrue(engine.cancelRequests >= 1)
    }

    @Test fun overallTurnCapIs300sAcrossSummaryPasses() = runBlocking {
        // Every pass streams steadily (never a first-token or idle stall) but together they pass the cap.
        val engine = SectionedEngine { _, onToken, e ->
            repeat(20) { if (!e.cancelled) { onToken("tok "); Thread.sleep(40) } }
            GenerateOutcome(cancelled = e.cancelled)
        }
        val manager = manager(engine, LocalStallDeadlines(firstTokenMs = 2_000, idleMs = 2_000, turnMs = 1_000))
        val stall = runCatching { generateSectioned(manager) }.exceptionOrNull() as LocalStreamStallError
        assertEquals(LocalStreamStallError.TURN, stall.deadline)
        assertEquals(1_000, stall.budgetMs)
        assertTrue(stall.elapsedMs >= 1_000)
        assertTrue("later passes never ran", engine.prompts.size < 6)
        assertTrue(engine.cancelRequests >= 1)
        assertTrue(stall.message!!.contains("stalled (turn)"))
    }

    @Test fun loadPhaseDeadlineIs180sAndRaisesTypedError() = runBlocking {
        val engine = object : ScriptedInferenceEngine("never reached") {
            override fun load(modelPath: String, contextTokens: Int): String? {
                Thread.sleep(700) // a native load cannot be interrupted; it returns past its budget
                return super.load(modelPath, contextTokens)
            }
        }
        val manager = manager(engine, LocalStallDeadlines(loadMs = 300))
        val stall = runCatching { manager.generate("hello", 64) {} }.exceptionOrNull() as LocalStreamStallError
        assertEquals(LocalStreamStallError.LOAD, stall.deadline)
        assertEquals(300, stall.budgetMs)
        assertTrue(stall.elapsedMs >= 300)
        assertEquals("no tokens were generated", 0, engine.generateCalls)
    }

    @Test fun loadAndTurnCapStallsFailTheTurnLikeAnyOtherStall() = runBlocking {
        // Load phase.
        run {
            val state = state()
            val turn = LocalReplyTurn(state, prior, "a1")
            var picked = true
            val engine = object : ScriptedInferenceEngine("x") {
                override fun load(modelPath: String, contextTokens: Int): String? { Thread.sleep(600); return null }
            }
            val manager = manager(engine, LocalStallDeadlines(loadMs = 250))
            val result = turn.answer(scope, manager, clearPicked = { picked = false }, keepWarm = { true }, onStart = {}, onFinally = {}) {
                manager.generate("hello", 64, onProgress = turn.progress) { turn.reply.append(it) }
            }
            assertEquals(LocalStreamStallError.LOAD, (result.exceptionOrNull() as LocalStreamStallError).deadline)
            assertTrue(state.value.error!!.contains("stalled (load)"))
            assertEquals("error bubble per the ruling", prior.size + 1, state.value.messages.size)
            assertEquals(state.value.error, state.value.messages.last().optString("text"))
            assertFalse("picked text is cleared", picked)
            assertTrue("unloaded even though keep-warm was requested", engine.unloadCount >= 1)
            assertEquals(CompanionPackStatus.READY, manager.status())
            assertEquals("", manager.lastError())
        }
        // Overall turn cap: steady streaming that never trips first-token or idle.
        run {
            val state = state()
            val turn = LocalReplyTurn(state, prior, "a1")
            var picked = true
            val engine = SectionedEngine { _, onToken, e ->
                repeat(20) { if (!e.cancelled) { onToken("tok "); Thread.sleep(40) } }
                GenerateOutcome(cancelled = e.cancelled)
            }
            val manager = manager(engine, LocalStallDeadlines(firstTokenMs = 2_000, idleMs = 2_000, turnMs = 700))
            val result = turn.answer(scope, manager, clearPicked = { picked = false }, keepWarm = { true }, onStart = {}, onFinally = {}) {
                generateSectioned(manager)
            }
            assertEquals(LocalStreamStallError.TURN, (result.exceptionOrNull() as LocalStreamStallError).deadline)
            assertTrue(state.value.error!!.contains("stalled (turn)"))
            assertEquals(prior.size + 1, state.value.messages.size)
            assertFalse(picked)
            assertTrue(engine.unloadCount >= 1)
            assertEquals(CompanionPackStatus.READY, manager.status())
            assertEquals("", manager.lastError())
        }
    }

    @Test fun stalledTurnUnloadsTheEngineAndLeavesPackReadyWithNoPackError() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = HangingEngine("Started then went quiet")
        val manager = manager(engine, LocalStallDeadlines(firstTokenMs = 5_000, idleMs = 200))
        assertTrue(answer(turn, manager).exceptionOrNull() is LocalStreamStallError)
        assertTrue("the engine was unloaded", engine.unloadCount >= 1)
        assertEquals(CompanionPackStatus.READY, manager.status())
        assertEquals("a stall is not a pack error", "", manager.lastError())
    }

    @Test fun cancelledTurnUnloadsTheEngineAndClearsPicked() = runBlocking {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        val engine = HangingEngine("Half of an answer")
        val manager = manager(engine)
        var picked = true
        val job = scope.launch {
            turn.answer(scope, manager, clearPicked = { picked = false }, keepWarm = { true }, onStart = {}, onFinally = {}) {
                manager.generate("hello", 64, onProgress = turn.progress) { turn.reply.append(it) }
            }
        }
        withTimeout(5_000) { while (state.value.liveLocalReply.isEmpty()) kotlinx.coroutines.delay(5) }
        job.cancelAndJoin()
        assertFalse("picked text is cleared", picked)
        assertTrue("the engine is unloaded after a cancellation", engine.unloadCount >= 1)
        assertEquals(CompanionPackStatus.READY, manager.status())
    }

    @Test fun keepWarmKeepsTheModelOnlyAfterASuccessfulTurn() = runBlocking {
        val ok = ScriptedInferenceEngine("A reply.")
        val warm = manager(ok)
        val success = turnAnswer(warm, keepWarm = true)
        assertTrue(success.isSuccess)
        assertEquals("a successful keep-warm turn keeps the model loaded", 0, ok.unloadCount)
        val failing = object : ScriptedInferenceEngine("") {
            override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit) = GenerateOutcome(error = "boom")
        }
        assertTrue(turnAnswer(manager(failing), keepWarm = true).isFailure)
        assertTrue("a failed turn unloads even when keep-warm holds", failing.unloadCount >= 1)
        val cold = ScriptedInferenceEngine("A reply.")
        assertTrue(turnAnswer(manager(cold), keepWarm = false).isSuccess)
        assertTrue("without keep-warm the model is released", cold.unloadCount >= 1)
    }

    private suspend fun turnAnswer(manager: CompanionPackManager, keepWarm: Boolean): Result<String> {
        val turn = LocalReplyTurn(state(), prior, "a1")
        return turn.answer(scope, manager, clearPicked = {}, keepWarm = { keepWarm }, onStart = {}, onFinally = {}) {
            manager.generate("hello", 64, onProgress = turn.progress) { turn.reply.append(it) }
            turn.reply.text()
        }
    }

    @Test fun pressureNeverWritesActivityAfterTheTurnHasClosed() {
        val state = state()
        val turn = LocalReplyTurn(state, prior, "a1")
        turn.discard()
        state.value = state.value.copy(activity = "Ready when you are")
        turn.pressure("Phone is warm — shorter answers on this phone.")
        turn.tick()
        assertEquals("Ready when you are", state.value.activity)
    }
}
