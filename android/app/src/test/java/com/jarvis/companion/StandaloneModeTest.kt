package com.jarvis.companion

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowAlarmManager
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FilterInputStream
import java.io.InputStream
import java.time.ZoneId
import java.time.ZonedDateTime

open class ScriptedInferenceEngine(
    var tokens: String = "Hello from this phone.",
) : LocalInferenceEngine {
    override val runtimeName: String = "scripted"
    var lastMaxTokens: Int = 0
    var lastPrompt: String = ""
    var lastContextTokens: Int = 0
    var unloadCount: Int = 0
    var loadOnMain: Boolean? = null
    var generateOnMain: Boolean? = null
    var truncateNext: Boolean = false
    @Volatile var cancelled: Boolean = false
    var kvClears: Int = 0
    var generateCalls: Int = 0
    override fun isRuntimeAvailable(): Boolean = true
    override fun requestCancel() { cancelled = true }
    override fun beginPass() { kvClears += 1 }
    open override fun tokenize(text: String): Int = (text.length + 3) / 4

    open override fun load(modelPath: String, contextTokens: Int): String? {
        lastContextTokens = contextTokens
        loadOnMain = android.os.Looper.myLooper() == android.os.Looper.getMainLooper()
        return null
    }
    open override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
        lastPrompt = prompt
        lastMaxTokens = maxTokens
        generateOnMain = android.os.Looper.myLooper() == android.os.Looper.getMainLooper()
        generateCalls += 1
        val text = if (prompt.contains("Summarize this section")) {
            "Section summary of picked text."
        } else {
            tokens
        }
        if (cancelled) return GenerateOutcome(cancelled = true)
        if (text.isNotEmpty()) onToken(text)
        if (cancelled) return GenerateOutcome(cancelled = true)
        if (truncateNext) {
            truncateNext = false
            return GenerateOutcome(truncated = true)
        }
        return GenerateOutcome()
    }
    override fun unload() { unloadCount += 1 }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33], shadows = [ReplaceAtomicFileShadow::class])
class StandaloneModeTest {
    private lateinit var context: Context
    private val now: ZonedDateTime =
        ZonedDateTime.of(2026, 10, 8, 15, 0, 0, 0, ZoneId.of("UTC"))

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences(StandaloneActions.PREFS, Context.MODE_PRIVATE).edit().clear().apply()
        context.getSharedPreferences("companion_pack", Context.MODE_PRIVATE).edit().clear().apply()
        context.getSharedPreferences("companion_pack_digest", Context.MODE_PRIVATE).edit().clear().apply()
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        Shadows.shadowOf(nm).setNotificationsEnabled(true)
        ShadowAlarmManager.setCanScheduleExactAlarms(true)
    }

    @Test
    fun reminderWithTimeSchedulesAlarmOnThisPhone() {
        val decision = StandaloneMode.classify("Remind me at 7:30 pm", now = now)
        assertEquals(StandaloneIntent.LOCAL_REMINDER, decision.intent)
        assertNotNull(decision.reminderAt)
        val result = StandaloneActions.scheduleReminder(context, "Remind me at 7:30 pm", decision.reminderAt!!).getOrThrow()
        assertTrue(result.message.contains("on this phone"))
        assertFalse(result.message.contains("Leader"))
        val alarm = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val scheduled = Shadows.shadowOf(alarm).scheduledAlarms
        assertTrue("expected a real AlarmManager alarm", scheduled != null && scheduled.isNotEmpty())
        val pending = scheduled[0].operation
        assertTrue("reminder alarm must be a broadcast PendingIntent", Shadows.shadowOf(pending).isBroadcastIntent)
        assertEquals(
            ReminderReceiver::class.java.name,
            Shadows.shadowOf(pending).savedIntent.component?.className,
        )
    }

    @Test
    fun reminderReceiverPostsExactlyOneNotificationAndMarksFired() {
        val at = ZonedDateTime.now(ZoneId.of("UTC")).minusMinutes(1)
        val result = StandaloneActions.scheduleReminder(context, "Remind me at 8:00 pm", at).getOrThrow()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancelAll()
        val receiver = ReminderReceiver()
        val intent = StandaloneActions.reminderBroadcastIntent(context, result.id)
        receiver.onReceive(context, intent)
        assertEquals(1, Shadows.shadowOf(manager).allNotifications.size)
        assertTrue(StandaloneActions.reminderIsFired(context, result.id))
        receiver.onReceive(context, intent)
        assertEquals(1, Shadows.shadowOf(manager).allNotifications.size)
    }

    @Test
    fun bootCompletedRearmsUnfiredReminders() {
        val at = ZonedDateTime.now(ZoneId.of("UTC")).plusHours(3)
        val result = StandaloneActions.scheduleReminder(context, "Remind me at 6:00 pm", at).getOrThrow()
        val alarm = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pending = PendingIntent.getBroadcast(
            context,
            result.id.hashCode(),
            StandaloneActions.reminderBroadcastIntent(context, result.id),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        alarm.cancel(pending)
        ReminderReceiver().onReceive(context, Intent(Intent.ACTION_BOOT_COMPLETED))
        val restored = Shadows.shadowOf(alarm).scheduledAlarms.firstOrNull { scheduled ->
            Shadows.shadowOf(scheduled.operation).isBroadcastIntent &&
                Shadows.shadowOf(scheduled.operation).savedIntent
                    .getStringExtra(StandaloneActions.EXTRA_REMINDER_ID) == result.id
        }
        assertNotNull("BOOT_COMPLETED must re-arm unfired reminders", restored)
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        assertTrue(Shadows.shadowOf(manager).allNotifications.isEmpty())
        assertFalse(StandaloneActions.reminderIsFired(context, result.id))
    }

    @Test
    fun fireReminderRefusesWhenDueMoreThanSixtySecondsAhead() {
        val at = ZonedDateTime.now(ZoneId.of("UTC")).plusHours(2)
        val result = StandaloneActions.scheduleReminder(context, "Remind me at 6:00 pm", at).getOrThrow()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancelAll()
        StandaloneActions.fireReminder(context, result.id)
        ReminderReceiver().onReceive(context, StandaloneActions.reminderBroadcastIntent(context, result.id))
        assertTrue(Shadows.shadowOf(manager).allNotifications.isEmpty())
        assertFalse(StandaloneActions.reminderIsFired(context, result.id))
    }

    @Test
    fun reminderReceiverIgnoresIntentsWithoutReminderAction() {
        val at = ZonedDateTime.now(ZoneId.of("UTC")).minusMinutes(1)
        val result = StandaloneActions.scheduleReminder(context, "Remind me at 8:00 pm", at).getOrThrow()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.cancelAll()
        val stray = Intent().putExtra(StandaloneActions.EXTRA_REMINDER_ID, result.id)
        ReminderReceiver().onReceive(context, stray)
        assertTrue(Shadows.shadowOf(manager).allNotifications.isEmpty())
        assertFalse(StandaloneActions.reminderIsFired(context, result.id))
    }

    @Test
    fun dueReminderPostsANotification() {
        val past = now.minusMinutes(2)
        StandaloneActions.scheduleReminder(context, "Remind me at 2:58 pm", past).getOrThrow()
        StandaloneActions.deliverDueReminders(context, now.toInstant().toEpochMilli())
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        assertTrue("expected a fired reminder notification", Shadows.shadowOf(manager).allNotifications.isNotEmpty())
    }

    @Test
    fun reminderWithoutTimeAsksOnce() {
        val decision = StandaloneMode.classify("Remind me to call the office", now = now)
        assertEquals(StandaloneIntent.REMINDER_NEEDS_TIME, decision.intent)
        assertNull(decision.reminderAt)
        assertTrue(StandaloneActions.reminderNeedsTimeCopy().contains("When should I remind you"))
    }

    @Test
    fun noteLandsInOfflineQueue() {
        val decision = StandaloneMode.classify("Remember this: the gate code is 9921")
        assertEquals(StandaloneIntent.LOCAL_NOTE, decision.intent)
        val queue = OutboxQueue(context, JvmAesOutboxQueueCrypto())
        queue.clear()
        val userId = "note-user-1"
        val assistantId = "note-asst-1"
        queue.append(
            StandaloneActions.userTurnJson(userId, "Remember this: the gate code is 9921", consequential = false, autoReplay = true),
        )
        queue.append(
            StandaloneActions.assistantTurnJson(assistantId, StandaloneActions.noteAckCopy(), consequential = false, autoReplay = true),
        )
        val pending = queue.readAll()
        assertEquals(2, pending.size)
        assertEquals(StandaloneActions.ORIGIN_USER, pending[0].optString("origin"))
        assertEquals(StandaloneActions.ORIGIN_ASSISTANT, pending[1].optString("origin"))
        assertEquals("note-user-1", pending[0].optString("client_message_id"))
    }

    @Test
    fun desktopOnlyIntentsQueueOrRefuseAndAreNeverMarkedDone() {
        val samples = listOf(
            "Send an email to the lawyer",
            "WhatsApp this to the group",
            "Run HexStrike on the lab box",
            "Generate an image of the cover",
            "Edit the files on the PC",
            "Use the desktop browser to open the portal",
            "Run this in the terminal",
            "Open Word on the desktop",
            "Spawn swarm workers for the chapter",
        )
        samples.forEach { prompt ->
            val decision = StandaloneMode.classify(prompt)
            assertEquals(prompt, StandaloneIntent.QUEUE_OR_REFUSE, decision.intent)
            assertTrue(StandaloneMode.desktopOnlyNeverDone(decision))
            val turn = StandaloneActions.userTurnJson("id-$prompt", prompt, decision.consequential, autoReplay = false)
            assertFalse(turn.optBoolean("done", false))
            assertFalse(StandaloneMode.shouldAutoReplay(turn))
        }
        assertEquals("I'll do that when the ANZU desktop is back.", StandaloneActions.queueOrRefuseCopy())
        assertFalse(StandaloneActions.queueOrRefuseCopy().contains("done"))
    }

    @Test
    fun consequentialQueuesDoNotAutoReplay() {
        val decision = StandaloneMode.classify("Send an email to payroll")
        assertTrue(decision.consequential)
        val turn = StandaloneActions.userTurnJson(
            "pay-1",
            "Send an email to payroll",
            consequential = true,
            autoReplay = false,
        )
        assertFalse(StandaloneMode.shouldAutoReplay(turn))
        val ordinary = StandaloneActions.userTurnJson("chat-1", "How is the weather", consequential = false, autoReplay = true)
        assertTrue(StandaloneMode.shouldAutoReplay(ordinary))
    }

    @Test
    fun pickedTextOver64KiBIsRefusedAndUnderCapIsInPrompt() {
        val over = ByteArray(StandaloneActions.PICKED_TEXT_MAX_BYTES + 1) { 'a'.code.toByte() }
        val under = "Title: North star\nANZU stays useful when the desktop is gone."
        assertTrue(over.size > StandalonePrompt.PICKED_TEXT_BUDGET_BYTES)
        val refused = StandaloneActions.pickedTextTooLargeCopy()
        assertTrue(refused.contains("64 KiB"))
        val prompt = StandalonePrompt.build(emptyList(), "Summarize this file", under)
        assertTrue(prompt.contains(under))
        assertTrue(StandalonePrompt.identifiesAnzu(prompt))

        val overFile = File(context.cacheDir, "over-cap.txt")
        overFile.writeBytes(over)
        val refusedRead = StandaloneActions.readPickedText(context, Uri.fromFile(overFile), "text/plain", "over-cap.txt")
        assertTrue(refusedRead.isFailure)
        assertTrue(refusedRead.exceptionOrNull()!!.message!!.contains("64 KiB"))

        val underFile = File(context.cacheDir, "under-cap.md")
        underFile.writeText(under)
        val loaded = StandaloneActions.readPickedText(context, Uri.fromFile(underFile), "text/markdown", "under-cap.md")
        assertEquals(under, loaded.getOrThrow())

        val counting = CountingInputStream(ByteArrayInputStream(over))
        val bounded = StandaloneActions.readBoundedUtf8(counting, StandaloneActions.PICKED_TEXT_MAX_BYTES)
        assertTrue(bounded.isFailure)
        assertTrue(
            "must not read more than cap+1 bytes, read=${counting.bytesRead}",
            counting.bytesRead <= StandaloneActions.PICKED_TEXT_MAX_BYTES + 1,
        )
    }

    @Test
    fun queuedMediaNameIsSanitizedDedupedAndCapped() {
        assertEquals("shot.jpg", StandaloneActions.safeMediaBasename("../foo/bar/shot.jpg"))
        assertFalse(StandaloneActions.safeMediaBasename("foo/../../../etc/passwd").contains(".."))
        assertFalse(StandaloneActions.safeMediaBasename("a\nb.jpg").contains("\n"))

        val dir = File(context.filesDir, "offline-media").apply { mkdirs() }
        File(dir, "note.jpg").writeText("first")
        assertEquals("note-1.jpg", StandaloneActions.uniqueMediaFile(dir, "note.jpg").name)

        val over = ByteArray(80) { 1 }
        val counting = CountingInputStream(ByteArrayInputStream(over))
        val thrown = runCatching {
            StandaloneActions.copyBounded(counting, java.io.ByteArrayOutputStream(), 40)
        }.exceptionOrNull()
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("32 MiB"))

        val source = File(context.cacheDir, "src.bin")
        source.writeBytes(ByteArray(16) { 2 })
        val first = StandaloneActions.storeQueuedMedia(context, Uri.fromFile(source), "../evil/photo.jpg")
        assertEquals("photo.jpg", first.name)
        val second = StandaloneActions.storeQueuedMedia(context, Uri.fromFile(source), "photo.jpg")
        assertEquals("photo-1.jpg", second.name)
        assertTrue(first.exists() && second.exists())
        assertTrue(first.readBytes().contentEquals(second.readBytes()))
    }

    @Test
    fun imageCaptureDoesNotClaimAnalysis() {
        val copy = StandaloneActions.mediaSavedCopy()
        assertFalse(StandaloneActions.claimsAlreadyAnalyzed(copy))
        assertTrue(copy.contains("when the ANZU desktop is back"))
        assertTrue(StandaloneActions.isImageOrVideo("image/jpeg", "shot.jpg"))
    }

    @Test
    fun reconnectSyncUsesStableIdsAndExistingOrigins() {
        val user = StandaloneActions.userTurnJson("11111111-1111-1111-1111-111111111111", "hello", false, true)
        val assistant = StandaloneActions.assistantTurnJson("22222222-2222-2222-2222-222222222222", "hi", false, true)
        assertEquals("device_offline", user.optString("origin"))
        assertEquals("device_local_draft", assistant.optString("origin"))
        assertEquals("11111111-1111-1111-1111-111111111111", user.optString("client_message_id"))
        assertEquals("11111111-1111-1111-1111-111111111111", user.optString("request_id"))
        assertTrue(StandaloneMode.shouldAutoReplay(user))
        val consequential = StandaloneActions.userTurnJson("c-1", "pay the invoice", true, false)
        assertFalse(StandaloneMode.shouldAutoReplay(consequential))
    }

    @Test
    fun fallbackOrderIsAbliteratedThenInstruct15bThenSelected3b() {
        val instruct15 = CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.INSTRUCT_15B_ID }
        val instruct3 = CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.INSTRUCT_3B_ID }
        assertTrue(CompanionPackCatalog.isLegalAllowlistRow(instruct15))
        assertFalse(CompanionPackCatalog.builtIn.any { CompanionPackCatalog.isAbliteratedCandidate(it) })

        val unnamedIllegal = instruct15.copy(id = "pending-abliterated", url = "", sha256 = "")
        assertFalse(CompanionPackCatalog.isLegalAllowlistRow(unnamedIllegal))
        assertNull(
            CompanionPackCatalog.resolveOfflinePack(
                listOf(unnamedIllegal, instruct15, instruct3),
                CompanionPackCatalog.INSTRUCT_3B_ID,
            ) { it.id == "pending-abliterated" },
        )

        val legalExtra = instruct15.copy(
            id = "future-abliterated-when-named",
            url = "https://example.invalid/legal.gguf",
            sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        val loaded = CompanionPackCatalog.resolveOfflinePack(
            listOf(legalExtra, instruct15, instruct3),
            CompanionPackCatalog.INSTRUCT_3B_ID,
        ) { pack -> pack.id == legalExtra.id || pack.id == CompanionPackCatalog.INSTRUCT_15B_ID }
        assertEquals(legalExtra.id, loaded?.id)

        val fallback15 = CompanionPackCatalog.resolveOfflinePack(
            CompanionPackCatalog.builtIn,
            CompanionPackCatalog.INSTRUCT_3B_ID,
        ) { it.id == CompanionPackCatalog.INSTRUCT_15B_ID }
        assertEquals(CompanionPackCatalog.INSTRUCT_15B_ID, fallback15?.id)

        val only3b = CompanionPackCatalog.resolveOfflinePack(
            CompanionPackCatalog.builtIn,
            CompanionPackCatalog.INSTRUCT_3B_ID,
        ) { it.id == CompanionPackCatalog.INSTRUCT_3B_ID }
        assertEquals(CompanionPackCatalog.INSTRUCT_3B_ID, only3b?.id)
    }

    @Test
    fun scriptedEngineReturnsRealTokensAndBlankIsError() {
        val engine = ScriptedInferenceEngine("The orchard gate is north.")
        val manager = CompanionPackManager(context, engine)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        val prompt = StandalonePrompt.build(
            listOf(JSONObject().put("role", "user").put("text", "Where is the gate?")),
            "Where is the gate?",
        )
        val out = StringBuilder()
        kotlinx.coroutines.runBlocking {
            manager.generate(prompt, DeviceInferenceGuard.BUDGET_CLEAR) { out.append(it) }
        }
        assertEquals("The orchard gate is north.", out.toString())
        assertTrue(engine.lastPrompt.contains("ANZU on this phone"))
        assertEquals(DeviceInferenceGuard.BUDGET_CLEAR, engine.lastMaxTokens)

        engine.tokens = ""
        val blank = StringBuilder()
        val thrown = runCatching {
            kotlinx.coroutines.runBlocking {
                manager.generate(prompt, DeviceInferenceGuard.BUDGET_CLEAR) { blank.append(it) }
            }
        }.exceptionOrNull()
        assertTrue(blank.toString().isEmpty())
        assertNotNull(thrown)
        assertTrue(thrown!!.message!!.contains("no tokens"))
    }

    @Test
    fun generateRunsLoadAndDecodeOffMain() {
        val engine = ScriptedInferenceEngine("ok")
        val manager = CompanionPackManager(context, engine)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        kotlinx.coroutines.runBlocking {
            manager.generate("hello", DeviceInferenceGuard.BUDGET_CLEAR) {}
        }
        assertEquals(false, engine.loadOnMain)
        assertEquals(false, engine.generateOnMain)
        assertFalse("normal finish must not call requestCancel", engine.cancelled)
    }

    @Test
    fun generateCancelBetweenTokensAborts() = runBlocking(Dispatchers.Default) {
        val started = java.util.concurrent.CountDownLatch(1)
        val engine = object : ScriptedInferenceEngine("abcdefghij") {
            override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
                lastPrompt = prompt
                lastMaxTokens = maxTokens
                generateOnMain = android.os.Looper.myLooper() == android.os.Looper.getMainLooper()
                generateCalls += 1
                onToken("abc")
                started.countDown()
                val deadline = System.nanoTime() + 3_000_000_000L
                while (!cancelled && System.nanoTime() < deadline) {
                    Thread.sleep(10)
                }
                if (cancelled) return GenerateOutcome(cancelled = true)
                onToken("def")
                return GenerateOutcome()
            }
        }
        val manager = CompanionPackManager(context, engine)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        val out = StringBuilder()
        var thrown: Throwable? = null
        val job = launch {
            try {
                manager.generate("hello", DeviceInferenceGuard.BUDGET_CLEAR) { out.append(it) }
            } catch (e: kotlinx.coroutines.CancellationException) {
                thrown = e
                throw e
            }
        }
        assertTrue(started.await(2, java.util.concurrent.TimeUnit.SECONDS))
        job.cancel()
        job.join()
        assertTrue("requestCancel must run while generate is blocked", engine.cancelled)
        assertTrue(thrown is kotlinx.coroutines.CancellationException)
        assertTrue(job.isCancelled)
        assertFalse(out.toString().contains("def"))
        assertEquals("abc", out.toString())
    }

    @Test
    fun contextTokensStayBoundedAndGrowWithRam() {
        assertEquals(2048, DeviceInferenceGuard.contextTokens(0, 3072))
        assertEquals(2048, DeviceInferenceGuard.contextTokens(3100, 3072))
        assertEquals(4096, DeviceInferenceGuard.contextTokens(5000, 3072))
        assertEquals(128, OfflinePromptPlanner.promptTokenBudget(2048, 2000))
        assertEquals(
            listOf(512, 512, 176),
            OfflinePromptPlanner.promptBatches(1200, 512),
        )
    }

    @Test
    fun overBudgetPickedTextIsSectionedThenAnswered() {
        val engine = object : ScriptedInferenceEngine("Final answer from summaries.") {
            override fun tokenize(text: String): Int =
                if (text.contains("PICKED-BLOCK")) 8000 else (text.length + 3) / 4
        }
        val manager = CompanionPackManager(context, engine)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        val picked = "PICKED-BLOCK " + "word ".repeat(400)
        val out = StringBuilder()
        val result = kotlinx.coroutines.runBlocking {
            manager.generate(
                prompt = StandalonePrompt.build(emptyList(), "Summarize this file", picked),
                maxTokens = 256,
                onToken = { out.append(it) },
                history = emptyList(),
                latest = "Summarize this file",
                pickedText = picked,
            )
        }
        assertTrue(result.sectioned)
        assertTrue(out.toString().contains("Final answer from summaries."))
        assertTrue("sectioned path must run 2+ section passes plus final", engine.generateCalls >= 3)
        assertEquals("KV cache must be cleared before every generate pass", engine.generateCalls, engine.kvClears)
    }

    @Test
    fun denseTokenizerReSplitsSectionsUnderBudget() {
        val tokenize = { text: String -> ((text.length * 2) / 5).coerceAtLeast(1) }
        val picked = "fn".repeat(4000)
        val plan = OfflinePromptPlanner.plan(
            history = emptyList(),
            latest = "Summarize this file",
            pickedText = picked,
            tokenize = tokenize,
            promptBudget = 400,
        )
        assertTrue(plan.sectioned)
        assertTrue(plan.sections.size >= 2)
        plan.sections.forEach { section ->
            assertTrue(
                tokenize(OfflinePromptPlanner.summarizeSectionPrompt(section)) <= 400,
            )
        }
        assertTrue(plan.summaryMaxTokens in 32..128)
    }

    @Test
    fun longHistoryIsTrimmedOldestFirstKeepingLatest() {
        val tokenize = { text: String -> ((text.length * 2) / 5).coerceAtLeast(1) }
        val history = (1..12).map { i ->
            JSONObject().put("role", "user").put("text", "turn-$i " + "word ".repeat(80))
        }
        val plan = OfflinePromptPlanner.plan(
            history = history,
            latest = "latest question",
            pickedText = null,
            tokenize = tokenize,
            promptBudget = 400,
        )
        assertTrue(plan.prompt.contains("latest question"))
        assertFalse(plan.prompt.contains("turn-1 "))
        assertTrue(tokenize(plan.prompt) <= 400)
        val cap = (400 / 2).coerceAtLeast(64)
        assertTrue(tokenize(StandalonePrompt.build(plan.history, "latest question", null)) <= cap)
        assertFalse(plan.clipped)
    }

    @Test
    fun latestAloneOverHalfBudgetIsClippedWithNotice() {
        val denseTokenize = { text: String -> ((text.length * 2) / 5).coerceAtLeast(1) }
        val latest = "latest question " + "word ".repeat(2000)
        val plan = OfflinePromptPlanner.plan(
            history = emptyList(),
            latest = latest,
            pickedText = null,
            tokenize = denseTokenize,
            promptBudget = 400,
        )
        val cap = (400 / 2).coerceAtLeast(64)
        assertTrue(plan.clipped)
        assertTrue(plan.latest.length < latest.length)
        assertTrue(latest.startsWith(plan.latest))
        assertTrue(denseTokenize(StandalonePrompt.build(emptyList(), plan.latest, null)) <= cap)
        assertTrue(plan.prompt.contains(plan.latest))
        assertFalse(plan.prompt.contains("word ".repeat(400)))
        val engine = object : ScriptedInferenceEngine("Clipped-path answer.") {
            override fun tokenize(text: String): Int = denseTokenize(text)
        }
        val manager = CompanionPackManager(context, engine)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        val out = StringBuilder()
        val result = kotlinx.coroutines.runBlocking {
            manager.generate(
                prompt = StandalonePrompt.build(emptyList(), latest, null),
                maxTokens = 256,
                onToken = { out.append(it) },
                history = emptyList(),
                latest = latest,
                pickedText = null,
            )
        }
        assertTrue(result.clipped)
        assertFalse(result.sectioned)
        assertFalse("normal finish must not call requestCancel", engine.cancelled)
        var reply = out.toString()
        if (result.clipped) reply = OfflinePromptPlanner.CLIPPED_NOTE + reply
        assertTrue(reply.startsWith(OfflinePromptPlanner.CLIPPED_NOTE))
        assertTrue(reply.contains("Clipped-path answer."))
    }

    @Test
    fun truncatedGenerateMarksTheAnswer() {
        val engine = ScriptedInferenceEngine("Partial.")
        engine.truncateNext = true
        val manager = CompanionPackManager(context, engine)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        val result = kotlinx.coroutines.runBlocking {
            manager.generate("hello", 32) {}
        }
        assertTrue(result.truncated)
    }

    @Test
    fun errorMidAnswerUnloadsAndClearsPicked() {
        val engine = object : ScriptedInferenceEngine("nope") {
            override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): GenerateOutcome {
                generateOnMain = android.os.Looper.myLooper() == android.os.Looper.getMainLooper()
                return GenerateOutcome(error = "boom mid-answer")
            }
        }
        val manager = CompanionPackManager(context, engine)
        val pack = CompanionPackCatalog.builtIn.first()
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        var picked: String? = "keep me"
        val started = java.util.concurrent.atomic.AtomicBoolean(false)
        val result = kotlinx.coroutines.runBlocking {
            withOfflineAnswerCleanup(
                packManager = manager,
                clearPicked = { picked = null },
                onStart = { started.set(true) },
                onFinally = {},
            ) {
                manager.generate("hello", 64) {}
            }
        }
        assertTrue(started.get())
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()!!.message!!.contains("boom"))
        assertNull(picked)
        assertTrue(engine.unloadCount >= 1)
    }

    @Test
    fun reminderWithoutNotificationsReturnsCopyNotThrow() {
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        Shadows.shadowOf(nm).setNotificationsEnabled(false)
        val at = now.plusHours(3)
        val scheduled = StandaloneActions.scheduleReminder(context, "Remind me at 7", at)
        assertTrue(scheduled.isFailure)
        val reply = scheduled.exceptionOrNull()?.message ?: StandaloneActions.reminderPermissionDeniedCopy()
        assertTrue(reply.contains("Notification permission is off"))
    }

    @Test
    fun exactAlarmGrantedUsesExactReminderCopy() {
        ShadowAlarmManager.setCanScheduleExactAlarms(true)
        val at = now.plusHours(2)
        val granted = StandaloneActions.scheduleReminder(context, "Remind me at 7:30 pm", at).getOrThrow()
        assertFalse(granted.inexact)
        assertTrue(granted.message.contains("for"))
        assertFalse(granted.message.contains("approximate"))
        assertFalse(granted.message.contains("system settings"))
        val copy = StandaloneActions.reminderOnThisPhoneCopy(at, inexact = false)
        assertFalse(copy.contains("approximate"))
    }

    @Test
    fun exactAlarmDeniedUsesApproximateCopy() {
        ShadowAlarmManager.setCanScheduleExactAlarms(false)
        val at = now.plusHours(2)
        val denied = StandaloneActions.scheduleReminder(context, "Remind me at 7:30 pm", at).getOrThrow()
        assertTrue(denied.inexact)
        assertTrue(denied.message.contains("approximate"))
        assertTrue(denied.message.contains("system settings"))
        val copy = StandaloneActions.reminderOnThisPhoneCopy(at, inexact = true)
        assertTrue(copy.contains("approximate"))
        assertTrue(copy.contains("Alarms & reminders"))
    }

    @Test
    fun generationBudgetIs512ClearAnd256UnderPressure() {
        assertEquals(512, DeviceInferenceGuard.generationBudget(80, charging = true, thermalPressure = false, powerSave = false))
        assertEquals(256, DeviceInferenceGuard.generationBudget(20, charging = false, thermalPressure = false, powerSave = false))
        assertEquals(256, DeviceInferenceGuard.generationBudget(90, charging = true, thermalPressure = true, powerSave = false))
    }

    @Test
    fun voiceTurnSpeaksOnlyWhenOnDeviceTtsSelected() {
        assertTrue(StandaloneMode.shouldSpeakVoiceReply(fromVoice = true, ttsRoute = TtsVoiceRoute.ON_DEVICE))
        assertFalse(StandaloneMode.shouldSpeakVoiceReply(fromVoice = false, ttsRoute = TtsVoiceRoute.ON_DEVICE))
        assertFalse(StandaloneMode.shouldSpeakVoiceReply(fromVoice = true, ttsRoute = TtsVoiceRoute.HOST_NEURAL))
        assertFalse(StandaloneMode.shouldSpeakVoiceReply(fromVoice = true, ttsRoute = TtsVoiceRoute.INSTALL))
    }

    @Test
    fun ownerFacingCopySaysAnzuNotJarvisOrLeader() {
        assertTrue(CompanionOfflineStatus.offlineBannerText(CompanionState(localPackStatus = "ready")).contains("Answering on this phone"))
        assertFalse(CompanionOfflineStatus.offlineBannerText(CompanionState(localPackStatus = "ready")).contains("Leader"))
        assertTrue(CompanionOfflineStatus.desktopBackBanner().startsWith("Desktop is back"))
        val blocked = CompanionRouting.decide(false, CompanionPackStatus.MISSING, null, false)
        assertTrue(blocked.reason.contains("ANZU desktop"))
        assertFalse(blocked.reason.contains("Jarvis"))
        val prompt = StandalonePrompt.build(emptyList(), "hello")
        assertTrue(StandalonePrompt.identifiesAnzu(prompt))
    }

    @Test
    fun secondResolveOfflinePackDoesNotRereadTheFile() {
        val pack = CompanionPackCatalog.builtIn.first { it.id == CompanionPackCatalog.INSTRUCT_15B_ID }
        var hashCalls = 0
        val hasher = FileHasher { hashCalls += 1; pack.sha256 }
        val cache = VerifiedDigestCache(hasher)
        val engine = ScriptedInferenceEngine()
        val manager = CompanionPackManager(context, engine, cache)
        manager.selectPack(pack.id)
        val file = manager.packFile(pack)
        file.parentFile?.mkdirs()
        file.writeBytes("gguf-fixture".toByteArray())
        cache.digestOf(file)
        assertEquals(1, hashCalls)
        assertEquals(pack.id, manager.resolveOfflinePack()?.id)
        assertEquals(pack.id, manager.resolveOfflinePack()?.id)
        assertEquals("second resolve must not re-hash", 1, hashCalls)
        assertEquals(1, cache.hashCallCount())
    }
}

private class CountingInputStream(wrapped: InputStream) : FilterInputStream(wrapped) {
    var bytesRead = 0
        private set

    override fun read(): Int {
        val value = super.read()
        if (value >= 0) bytesRead += 1
        return value
    }

    override fun read(b: ByteArray, off: Int, len: Int): Int {
        val n = super.read(b, off, len)
        if (n > 0) bytesRead += n
        return n
    }
}
