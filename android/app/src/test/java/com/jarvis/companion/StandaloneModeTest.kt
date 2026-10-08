package com.jarvis.companion

import android.app.AlarmManager
import android.content.Context
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
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.time.ZoneId
import java.time.ZonedDateTime

class ScriptedInferenceEngine(
    var tokens: String = "Hello from this phone.",
) : LocalInferenceEngine {
    override val runtimeName: String = "scripted"
    var lastMaxTokens: Int = 0
    var lastPrompt: String = ""
    override fun isRuntimeAvailable(): Boolean = true
    override fun load(modelPath: String, contextTokens: Int): String? = null
    override fun generate(prompt: String, maxTokens: Int, onToken: (String) -> Unit): String? {
        lastPrompt = prompt
        lastMaxTokens = maxTokens
        if (tokens.isNotEmpty()) onToken(tokens)
        return null
    }
    override fun unload() {}
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class StandaloneModeTest {
    private lateinit var context: Context
    private val now: ZonedDateTime =
        ZonedDateTime.of(2026, 10, 8, 15, 0, 0, 0, ZoneId.of("UTC"))

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences(StandaloneActions.PREFS, Context.MODE_PRIVATE).edit().clear().apply()
        context.getSharedPreferences("companion_pack", Context.MODE_PRIVATE).edit().clear().apply()
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
        kotlinx.coroutines.runBlocking {
            manager.generate(prompt, DeviceInferenceGuard.BUDGET_CLEAR) { blank.append(it) }
        }
        assertTrue(blank.toString().isEmpty())
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
}
