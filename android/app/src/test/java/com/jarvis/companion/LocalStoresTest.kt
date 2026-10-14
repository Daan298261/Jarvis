package com.jarvis.companion

import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33], shadows = [ReplaceAtomicFileShadow::class])
class LocalStoresTest {
    private val context get() = ApplicationProvider.getApplicationContext<android.content.Context>()
    private var now = 1_000L

    @Before
    fun clean() {
        File(context.noBackupFilesDir, "local-conversations").delete()
        File(context.noBackupFilesDir, "local-notes").delete()
    }

    @Test
    fun conversationsPersistAcrossInstancesNewestFirst() {
        val crypto = JvmAesOutboxQueueCrypto()
        val store = LocalConversationStore(context, crypto, clock = { now })
        val first = store.create("What is the capital of France?")
        store.append(first, StandaloneActions.chatMessage("u1", "user", "What is the capital of France?", StandaloneActions.ORIGIN_USER))
        now = 2_000L
        val second = store.create("Second chat", linkedDesktopId = "desk-1")
        store.append(second, StandaloneActions.chatMessage("u2", "user", "hi", StandaloneActions.ORIGIN_USER))
        now = 3_000L
        store.append(first, StandaloneActions.chatMessage("a1", "assistant", "Paris.", StandaloneActions.ORIGIN_ASSISTANT))

        val reopened = LocalConversationStore(context, crypto, clock = { now })
        val list = reopened.conversations()
        assertEquals(listOf(first, second), list.map { it.getString("id") })
        assertTrue(list.all { it.getBoolean("local") })
        assertEquals("What is the capital of France?", list[0].getString("title"))
        assertEquals(listOf("user", "assistant"), reopened.messages(first).map { it.getString("role") })
        assertEquals("Paris.", reopened.messages(first)[1].getString("text"))
        assertEquals("desk-1", reopened.linkedDesktopId(second))
        assertNull(reopened.linkedDesktopId(first))
    }

    @Test
    fun storedBytesAreEncrypted() {
        val store = LocalConversationStore(context, JvmAesOutboxQueueCrypto(), clock = { now })
        val id = store.create("case 4471 suspect address")
        store.append(id, StandaloneActions.chatMessage("u", "user", "case 4471 suspect address", StandaloneActions.ORIGIN_USER))
        val raw = File(context.noBackupFilesDir, "local-conversations").readBytes().toString(Charsets.ISO_8859_1)
        assertFalse(raw.contains("4471"))
    }

    @Test
    fun localIdsLinkAndDelete() {
        val store = LocalConversationStore(context, JvmAesOutboxQueueCrypto(), clock = { now })
        val id = store.create("x")
        assertTrue(LocalConversationStore.isLocal(id))
        assertFalse(LocalConversationStore.isLocal("abc"))
        assertFalse(LocalConversationStore.isLocal(null))
        store.linkDesktop(id, "desk-9")
        assertEquals("desk-9", store.linkedDesktopId(id))
        store.delete(id)
        assertFalse(store.exists(id))
        assertTrue(store.messages(id).isEmpty())
    }

    @Test
    fun localConversationNeverLinksToAnotherLocalId() {
        val store = LocalConversationStore(context, JvmAesOutboxQueueCrypto(), clock = { now })
        val id = store.create("x", linkedDesktopId = "local-other")
        assertNull(store.linkedDesktopId(id))
    }

    @Test
    fun messageHistoryIsBounded() {
        val store = LocalConversationStore(context, JvmAesOutboxQueueCrypto(), clock = { now })
        val id = store.create("long")
        repeat(LocalConversationStore.MAX_MESSAGES + 5) { i ->
            store.append(id, StandaloneActions.chatMessage("m$i", "user", "m$i", StandaloneActions.ORIGIN_USER))
        }
        val messages = store.messages(id)
        assertEquals(LocalConversationStore.MAX_MESSAGES, messages.size)
        assertEquals("m5", messages.first().getString("text"))
    }

    @Test
    fun titlesAreShortSingleLine() {
        assertEquals("Conversation on this phone", LocalConversationStore.titleFor("   "))
        assertEquals("hello world", LocalConversationStore.titleFor("hello   world\nsecond line"))
        val long = LocalConversationStore.titleFor("a".repeat(200))
        assertEquals(LocalConversationStore.TITLE_CHARS, long.length)
        assertTrue(long.endsWith("…"))
    }

    @Test
    fun notesPersistNewestFirstAndDelete() {
        val crypto = JvmAesOutboxQueueCrypto()
        val notes = LocalNotesStore(context, crypto, clock = { now })
        val first = notes.add("buy milk")
        now = 5_000L
        notes.add("  call the lab  ")
        val reopened = LocalNotesStore(context, crypto, clock = { now })
        assertEquals(listOf("call the lab", "buy milk"), reopened.notes().map { it.getString("text") })
        reopened.delete(first.getString("id"))
        assertEquals(listOf("call the lab"), reopened.notes().map { it.getString("text") })
    }

    @Test(expected = IllegalArgumentException::class)
    fun emptyNoteIsRejected() {
        LocalNotesStore(context, JvmAesOutboxQueueCrypto(), clock = { now }).add("   ")
    }
}
