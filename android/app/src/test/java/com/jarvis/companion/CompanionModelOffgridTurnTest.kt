package com.jarvis.companion

import android.content.Intent
import android.os.BatteryManager
import kotlinx.coroutines.Job
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/**
 * RFC-0235 turn lifecycle through the real [CompanionModel]: `sendOffgrid` -> `sendOffline`, the real
 * `sendLock`, the failed-turn error bubble, the load and turn deadlines, the memory-pressure warning in
 * the phone-tool path, and what a desktop poll may touch while a local answer runs.
 */
@RunWith(KeystoreRobolectricRunner::class)
@Config(sdk = [34], application = JarvisApp::class, shadows = [ReplaceAtomicFileShadow::class])
class CompanionModelOffgridTurnTest : CompanionModelHarness() {
    override val deadlines = LocalStallDeadlines(firstTokenMs = 5_000, idleMs = 300, loadMs = 400, turnMs = 5_000)

    private fun finished() = !model.state.value.busy && !model.state.value.offlineAnswering

    @Test fun sendOffgridLandsTheReplyAndClearsTheHomePreview() {
        model.sendOffgrid("hello there")
        pump { assistantTexts().any { it.startsWith("Hello from this phone") } && finished() }
        val state = model.state.value
        assertEquals("", state.liveLocalReply)
        assertNull(state.error)
        assertEquals(listOf("hello there", "Hello from this phone."), texts())
        assertFalse("the real send lock is released", sendLock().isLocked)
        // The saved reply is in the local conversation and the offline queue.
        val saved = LocalConversationStore(context).messages(state.conversationId!!).map { it.optString("text") }
        assertTrue(saved.contains("Hello from this phone."))
        assertEquals(2, OutboxQueue(context).readAll().size)
    }

    @Test fun failedTurnKeepsItsErrorBubbleAndClearsOnlyThePartialAndHomePreview() {
        engine.mode = "error"
        model.sendOffgrid("hello there")
        pump { model.state.value.error != null && finished() }
        val state = model.state.value
        assertEquals("model crashed mid-answer", state.error)
        assertEquals("", state.liveLocalReply)
        assertEquals(listOf("hello there", "model crashed mid-answer"), texts())
        assertEquals("assistant", state.messages.last().optString("role"))
        assertFalse("the partial is in no message", texts().any { it.contains("Half an answer") })
        assertFalse(sendLock().isLocked)
    }

    @Test fun failedTurnErrorBubbleIsNeverSavedOrQueued() {
        engine.mode = "error"
        model.sendOffgrid("hello there")
        pump { model.state.value.error != null && finished() }
        val conversationId = model.state.value.conversationId!!
        val saved = LocalConversationStore(context).messages(conversationId).map { it.optString("text") }
        assertFalse("the error bubble is not in the local conversation", saved.contains("model crashed mid-answer"))
        assertEquals("only the owner's own message was saved", listOf("hello there"), saved)
        assertEquals("nothing is queued for the desktop", 0, OutboxQueue(context).readAll().size)
        assertEquals(0, model.state.value.offlineQueueDepth)
    }

    @Test fun cancelledTurnLeavesNoPartialAndNoErrorAndReleasesTheLock() {
        engine.mode = "hang"
        val job: Job = model.sendOffgrid("hello there")
        pump { model.state.value.liveLocalReply == "Half an answer" }
        assertTrue(sendLock().isLocked)
        job.cancel()
        pump { !model.state.value.offlineAnswering && !sendLock().isLocked }
        val state = model.state.value
        assertEquals("", state.liveLocalReply)
        assertEquals(listOf("hello there"), texts())
        assertNull("a cancel is not an error", state.error)
        assertTrue("native decode was asked to stop", engine.cancelRequests >= 1)
    }

    @Test fun stallThroughSendOffgridReleasesTheRealSendLock() {
        engine.mode = "hang"
        model.sendOffgrid("hello there")
        pump { model.state.value.error != null && finished() }
        val state = model.state.value
        assertTrue(state.error!!.contains("stalled (idle)"))
        assertTrue("native decode was asked to stop", engine.cancelRequests >= 1)
        assertEquals(listOf("hello there", state.error), texts())
        assertEquals("", state.liveLocalReply)
        assertFalse("CompanionModel.sendLock is released", sendLock().isLocked)
        assertEquals("a stall never marks the pack failed", "", model.packManager.lastError())
        assertEquals(CompanionPackStatus.READY, model.packManager.status())
        assertTrue("the engine was unloaded", engine.unloadCount >= 1)
        // The next message is not blocked behind the stalled one.
        engine.mode = "ok"
        model.sendOffgrid("try again")
        pump { assistantTexts().any { it == "Hello from this phone." } && finished() }
        assertNull(model.state.value.error)
    }

    @Test fun loadDeadlineThroughSendOffgridRaisesTheTypedErrorAndReleasesTheLock() {
        engine.loadDelayMs = 3_000
        model.sendOffgrid("hello there")
        pump { model.state.value.error != null && finished() }
        val error = model.state.value.error!!
        assertTrue(error, error.contains("stalled (load)"))
        assertEquals(listOf("hello there", error), texts())
        assertFalse(sendLock().isLocked)
        assertEquals("", model.packManager.lastError())
        assertTrue(engine.unloadCount >= 1)
        engine.loadDelayMs = 0
        model.sendOffgrid("try again")
        pump { assistantTexts().any { it == "Hello from this phone." } && finished() }
    }

    @Test fun phoneToolPassesShowTheMemoryPressureWarning() {
        context.getSharedPreferences("phone_tools", android.content.Context.MODE_PRIVATE).edit().putBoolean("enabled", true).commit()
        context.sendStickyBroadcast(Intent(Intent.ACTION_BATTERY_CHANGED)
            .putExtra(BatteryManager.EXTRA_LEVEL, 20).putExtra(BatteryManager.EXTRA_SCALE, 100)
            .putExtra(BatteryManager.EXTRA_STATUS, BatteryManager.BATTERY_STATUS_DISCHARGING))
        engine.mode = "hold"
        model.send("open the settings")
        pump { model.state.value.activity.startsWith("Battery is at 20%") }
        // The ticker keeps the warning in front of the phone step on every tick.
        pump { model.state.value.activity.startsWith("Battery is at 20% — shorter answers on this phone. · Phone step 1/10") }
        engine.released = true
        pump { finished() && assistantTexts().contains("Done.") }
        // After the turn the line is no longer the warning.
        assertFalse(model.state.value.activity.contains("Battery"))
    }

    @Test fun desktopPollDuringALocalAnswerLeavesActivityAndMessagesAlone() {
        val answering = CompanionState(offlineAnswering = true, activity = "Writing reply · 3s", conversationId = "local-1",
            messages = listOf(org.json.JSONObject().put("role", "assistant").put("text", "streamed so far")))
        val polled = listOf(org.json.JSONObject().put("role", "assistant").put("text", "desktop copy"))
        assertEquals("Writing reply · 3s", DesktopRefreshRules.activity(answering, voiceTaskActive = false, desktopActivity = "Desktop busy"))
        assertEquals("Writing reply · 3s", DesktopRefreshRules.activity(answering.copy(recording = true), voiceTaskActive = true, desktopActivity = null))
        assertEquals(answering.messages, DesktopRefreshRules.messages(answering, "local-1", polled))
        // Not answering: the poll behaves as before.
        val idle = answering.copy(offlineAnswering = false)
        assertEquals("Desktop busy", DesktopRefreshRules.activity(idle, false, "Desktop busy"))
        assertEquals("Ready when you are", DesktopRefreshRules.activity(idle, false, null))
        assertEquals("Desktop is processing your request…", DesktopRefreshRules.activity(idle, true, null))
        assertEquals(polled, DesktopRefreshRules.messages(idle, "local-1", polled))
        assertEquals(idle.messages, DesktopRefreshRules.messages(idle, "another", polled))
    }
}
