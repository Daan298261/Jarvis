package com.jarvis.companion

import android.content.Context
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class NoticeStoreTest {
    private lateinit var context: Context
    private var now = 1_000_000L
    private fun prefs() = context.getSharedPreferences(NoticeStore.PREFS, Context.MODE_PRIVATE)
    private fun store(maxEvents: Int = 50, maxAgeMs: Long = 7L * 24 * 3600 * 1000) = NoticeStore(prefs(), { now }, maxEvents, maxAgeMs)
    private val offline = LiveCondition(NoticeKind.DESKTOP_OFFLINE, NoticeSeverity.WARNING, "ANZU desktop unreachable", listOf(NoticeAction.SCAN_WIFI))

    @Before fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        prefs().edit().clear().commit()
    }

    @Test fun live_condition_appears_unread_and_clears_when_resolved() {
        val s = store()
        s.syncLive(listOf(offline))
        val n = s.notices.value.single()
        assertTrue(n.live); assertFalse(n.read); assertEquals(1, s.unreadCount())
        assertEquals(listOf(NoticeAction.SCAN_WIFI), n.actions)
        s.syncLive(emptyList())
        assertTrue(s.notices.value.isEmpty())
        assertEquals(0, s.unreadCount())
    }

    @Test fun live_condition_with_new_text_updates_and_is_unread_again() {
        val s = store()
        s.syncLive(listOf(offline))
        s.markAllRead()
        now += 1000
        s.syncLive(listOf(offline)) // unchanged: stays read, keeps its time
        assertTrue(s.notices.value.single().read)
        assertEquals(1_000_000L, s.notices.value.single().timeMillis)
        s.syncLive(listOf(offline.copy(body = "downloading companion model (40%)")))
        val n = s.notices.value.single()
        assertFalse(n.read); assertEquals(now, n.timeMillis); assertEquals("downloading companion model (40%)", n.body)
    }

    @Test fun download_progress_keeps_read_state_and_position() {
        val s = store()
        s.syncLive(listOf(offline.copy(body = "downloading companion model (40%)")))
        s.markAllRead()
        now += 1000
        s.syncLive(listOf(offline.copy(body = "downloading companion model (41%)")))
        assertTrue(s.notices.value.single().read)
        assertEquals(1_000_000L, s.notices.value.single().timeMillis)
        assertEquals("downloading companion model (41%)", s.notices.value.single().body)
    }

    @Test fun dismissed_live_stays_hidden_across_restart_until_it_changes_or_recurs() {
        store().apply { syncLive(listOf(offline)); dismiss(notices.value.single().id) }
        val restarted = store()
        restarted.syncLive(listOf(offline))
        assertTrue(restarted.notices.value.isEmpty())
        restarted.syncLive(emptyList())
        restarted.syncLive(listOf(offline))
        assertEquals(1, restarted.notices.value.size)
    }

    @Test fun read_state_of_live_notice_survives_restart() {
        store().apply { syncLive(listOf(offline)); markAllRead() }
        val restarted = store()
        restarted.syncLive(listOf(offline))
        assertTrue(restarted.notices.value.single().read)
        assertEquals(0, restarted.unreadCount())
    }

    @Test fun events_are_dated_persisted_capped_and_aged_out() {
        val s = store(maxEvents = 3, maxAgeMs = 10_000)
        repeat(5) { i -> now += 3_000; s.postEvent(NoticeKind.ERROR, NoticeSeverity.ERROR, "error $i") }
        assertEquals(listOf("error 4", "error 3", "error 2"), s.notices.value.map { it.body })
        val restarted = store(maxEvents = 3, maxAgeMs = 10_000)
        assertEquals(listOf("error 4", "error 3", "error 2"), restarted.notices.value.map { it.body })
        now += 7_000 // error 2 is now 13 s old (> 10 s), error 3 exactly 10 s
        val later = store(maxEvents = 3, maxAgeMs = 10_000)
        assertEquals(listOf("error 4", "error 3"), later.notices.value.map { it.body })
    }

    @Test fun identical_event_within_two_seconds_is_folded() {
        val s = store()
        s.postEvent(NoticeKind.ERROR, NoticeSeverity.ERROR, "Microphone is unavailable")
        now += 500
        s.postEvent(NoticeKind.ERROR, NoticeSeverity.ERROR, "Microphone is unavailable")
        assertEquals(1, s.notices.value.size)
        now += 5_000
        s.postEvent(NoticeKind.ERROR, NoticeSeverity.ERROR, "Microphone is unavailable")
        assertEquals(2, s.notices.value.size)
    }

    @Test fun dismiss_and_clear_all_persist() {
        val s = store()
        s.postEvent(NoticeKind.ERROR, NoticeSeverity.ERROR, "a"); now += 3000
        s.postEvent(NoticeKind.ERROR, NoticeSeverity.ERROR, "b")
        s.syncLive(listOf(offline))
        s.dismiss(s.notices.value.first { it.body == "a" }.id)
        assertEquals(setOf("b", offline.body), store().also { it.syncLive(listOf(offline)) }.notices.value.map { it.body }.toSet())
        s.clearAll()
        assertTrue(s.notices.value.isEmpty())
        val restarted = store()
        restarted.syncLive(listOf(offline))
        assertTrue(restarted.notices.value.isEmpty())
    }

    @Test fun mark_all_read_persists_for_events() {
        store().apply { postEvent(NoticeKind.ERROR, NoticeSeverity.ERROR, "x"); markAllRead() }
        assertEquals(0, store().unreadCount())
    }

    @Test fun rules_map_state_to_conditions() {
        val unpairedOffline = NoticeRules.conditions(CompanionState(), paired = false)
        assertEquals(listOf(NoticeKind.DESKTOP_OFFLINE), unpairedOffline.map { it.kind })
        assertEquals(listOf(NoticeAction.PAIR), unpairedOffline.single().actions)
        assertEquals(NoticeSeverity.WARNING, unpairedOffline.single().severity)

        val phone = NoticeRules.conditions(CompanionState(localPackStatus = CompanionPackStatus.READY), paired = true).single()
        assertEquals(NoticeSeverity.INFO, phone.severity)
        assertEquals(listOf(NoticeAction.SCAN_WIFI), phone.actions)

        val online = CompanionState(leaderReachable = true, connected = true)
        assertTrue(NoticeRules.conditions(online, true).isEmpty())

        val busy = NoticeRules.conditions(online.copy(pendingMessage = true, localPackError = "Download failed (503)",
            voicePackError = "Download checksum mismatch"), true)
        assertEquals(listOf(NoticeKind.PENDING_MESSAGE, NoticeKind.MODEL_DOWNLOAD, NoticeKind.VOICE_DOWNLOAD), busy.map { it.kind })
        assertEquals(listOf(NoticeAction.RETRY_PENDING, NoticeAction.DISCARD_PENDING), busy[0].actions)
        assertEquals(listOf(NoticeAction.RETRY_MODEL_DOWNLOAD), busy[1].actions)
        assertEquals(listOf(NoticeAction.RETRY_VOICE_DOWNLOAD), busy[2].actions)

        // A retry in flight hides the stale failure until it finishes.
        val retrying = NoticeRules.conditions(online.copy(localPackError = "x", localPackStatus = CompanionPackStatus.DOWNLOADING,
            voicePackError = "y", voiceSttStatus = CompanionVoicePackStatus.DOWNLOADING), true)
        assertTrue(retrying.isEmpty())

        assertEquals(listOf(NoticeAction.OPEN_APP_SETTINGS), NoticeRules.errorActions("Microphone permission is required for on-device voice"))
        assertTrue(NoticeRules.errorActions("Upload failed").isEmpty())
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class NotificationsScreenTest {
    @get:Rule val compose = createComposeRule()

    private val pending = Notice("live-PENDING_MESSAGE", NoticeKind.PENDING_MESSAGE, NoticeSeverity.WARNING, null, 1_700_000_000_000L,
        live = true, read = false, actions = listOf(NoticeAction.RETRY_PENDING, NoticeAction.DISCARD_PENDING))
    private val error = Notice("evt-1", NoticeKind.ERROR, NoticeSeverity.ERROR, "Upload failed", 1_700_000_100_000L,
        live = false, read = true, actions = emptyList())

    @Test fun shows_title_severity_body_and_runs_actions() {
        val actions = mutableListOf<NoticeAction>(); val dismissed = mutableListOf<String>(); var cleared = 0
        compose.setContent { NotificationsScreen(listOf(error, pending), true, { actions += it }, { dismissed += it }, { cleared++ }) }
        compose.onNodeWithText("Message waiting for confirmation").assertExists()
        compose.onNodeWithText("WARNING").assertExists()
        compose.onNodeWithText("ERROR").assertExists()
        compose.onNodeWithText("Upload failed").assertExists()
        compose.onNodeWithTag("unread_${pending.id}").assertExists()
        compose.onNodeWithTag("unread_${error.id}").assertDoesNotExist()
        compose.onNodeWithText("Retry safely").performClick()
        assertEquals(listOf(NoticeAction.RETRY_PENDING), actions)
        // Discard needs a confirmation first.
        compose.onNodeWithText("Discard").performClick()
        assertEquals(1, actions.size)
        compose.onNodeWithText("Discard pending message?").assertExists()
        compose.onNodeWithText("Keep").performClick()
        assertEquals(1, actions.size)
        compose.onNodeWithText("Discard").performClick()
        compose.onAllNodes(androidx.compose.ui.test.hasText("Discard") and androidx.compose.ui.test.hasAnyAncestor(androidx.compose.ui.test.isDialog()))[0].performClick()
        assertEquals(listOf(NoticeAction.RETRY_PENDING, NoticeAction.DISCARD_PENDING), actions)
        compose.onAllNodes(androidx.compose.ui.test.hasText("Dismiss"))[0].performClick()
        assertEquals(1, dismissed.size)
        compose.onNodeWithText("Clear all").performClick()
        assertEquals(1, cleared)
    }

    @Test fun actions_disabled_while_busy() {
        compose.setContent { NotificationsScreen(listOf(pending), false, {}, {}, {}) }
        compose.onNodeWithText("Retry safely").assertIsNotEnabled()
    }

    @Test fun empty_state() {
        compose.setContent { NotificationsScreen(emptyList(), true, {}, {}, {}) }
        compose.onNodeWithText("No notifications", substring = true).assertExists()
        compose.onNodeWithText("Clear all").assertDoesNotExist()
    }

    @Test fun ongoing_notice_remains_accessible_after_reading() {
        var clicked = false
        compose.setContent { HomeNoticeIndicator(0, ongoing = true) { clicked = true } }
        compose.onNodeWithTag("home_notice_indicator").performClick()
        assertTrue(clicked)
    }

    @Test fun home_indicator_shows_count_and_hides_when_all_read() {
        var unread by androidx.compose.runtime.mutableStateOf(3)
        var clicks = 0
        compose.setContent { HomeNoticeIndicator(unread) { clicks++ } }
        compose.onNodeWithText("3").assertExists()
        compose.onNodeWithTag("home_notice_indicator").performClick()
        assertEquals(1, clicks)
        unread = 0
        compose.onNodeWithTag("home_notice_indicator").assertDoesNotExist()
    }

    @Config(qualifiers = "nl")
    @Test fun dutch_strings() {
        compose.setContent { NotificationsScreen(listOf(pending), true, {}, {}, {}) }
        compose.onNodeWithText("Meldingen").assertExists()
        compose.onNodeWithText("Bericht wacht op bevestiging").assertExists()
        compose.onNodeWithText("Veilig opnieuw proberen").assertExists()
        compose.onNodeWithText("WAARSCHUWING").assertExists()
    }
}
