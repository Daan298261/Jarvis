package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PhoneMemoryStoreTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    private val crypto = JvmAesOutboxQueueCrypto()
    private val stores = mutableListOf<PhoneMemoryStore>()
    private var now = 1000L
    private fun store() = PhoneMemoryStore(context, crypto, clock = { now++ }).also { stores += it }
    private fun message(id: String, text: String, role: String = "user") = JSONObject().put("id", id).put("role", role).put("text", text)
    @Before fun clean() {
        listOf(PhoneMemoryStore.DB_NAME, PhoneMemoryStore.DB_NAME + "-wal", PhoneMemoryStore.DB_NAME + "-shm").forEach { File(context.noBackupFilesDir, it).delete() }
    }
    @After fun close() { stores.forEach { it.close() } }
    @Test fun archivePersistsAllRowsAndSummariesAcrossReopen() {
        val db = store(); db.upsertChat("chat", "Archive")
        repeat(530) { db.append("chat", message("m$it", "archive message number $it")) }
        db.close()
        val reopened = store()
        assertEquals(530, reopened.summary("chat")!!.getInt("message_count"))
        assertEquals("m0", reopened.messages("chat").first().getString("id"))
        assertEquals("m529", reopened.messages("chat", 40, 520).last().getString("id"))
        assertTrue(reopened.summary("chat")!!.getJSONArray("excerpts").length() <= 12)
    }
    @Test fun migrationIsIdempotentAndDoesNotResurrectDeletedChat() {
        val db = store()
        val legacy = JSONObject().put("conversations", JSONArray().put(JSONObject().put("id", "legacy").put("title", "Earlier")
            .put("messages", JSONArray().put(message("u1", "old archive fact")))))
        db.migrateLegacy(legacy); db.migrateLegacy(legacy)
        assertEquals(1, db.summary("legacy")!!.getInt("message_count"))
        db.deleteChat("legacy"); db.migrateLegacy(legacy)
        assertNull(db.chat("legacy")); assertTrue(db.recall("archive fact", "", null).isEmpty())
    }
    @Test fun globalInstructionsApplyButProjectsCannotLeakQuotes() {
        val db = store()
        db.saveProject("", "All chats", "Global owner note", "Use concise Dutch")
        db.saveProject("p1", "Travel", "Train trip", "Use kilometres")
        db.saveProject("p2", "Private", "Do not mix", "Use English")
        db.upsertChat("a", "Journey", "p1"); db.append("a", message("m", "The violet parcel is at Utrecht station"))
        db.upsertChat("b", "Other", "p2"); db.append("b", message("m", "The violet parcel is at Rotterdam station"))
        val recall = db.recall("violet parcel", "p1", null)
        assertEquals(listOf("a"), recall.map { it.getString("chat_id") })
        val context = db.context("violet parcel", "p1", "new")
        assertTrue(context.contains("Use concise Dutch")); assertTrue(context.contains("Use kilometres"))
        assertFalse(context.contains("Rotterdam")); assertFalse(context.contains("Use English"))
    }
    @Test fun replayDoesNotDuplicateAndStreamingUpdatesReplaceSearchTerms() {
        val db = store(); db.upsertChat("a", "Stream")
        db.append("a", message("u", "firstdraft")); db.append("a", message("u", "firstdraft"))
        db.append("a", message("u", "completeanswer"))
        assertEquals(1, db.summary("a")!!.getInt("message_count"))
        assertTrue(db.recall("firstdraft", "", null).isEmpty())
        assertEquals(1, db.recall("completeanswer", "", null).size)
    }
    @Test fun contentAndIndexNeverStorePlaintextAndDeleteCascades() {
        val db = store(); db.upsertChat("id", "classified-garden-location")
        db.saveProject("p", "secret-project-name", "confidential-note-data", "specific-private-instructions")
        db.append("id", message("m", "classified-garden-location"))
        listOf(PhoneMemoryStore.DB_NAME, PhoneMemoryStore.DB_NAME + "-wal").map { File(context.noBackupFilesDir, it) }.filter { it.exists() }.forEach { file ->
            val raw = file.readBytes().toString(Charsets.ISO_8859_1)
            listOf("classified-garden-location", "secret-project-name", "confidential-note-data", "specific-private-instructions").forEach { assertFalse(file.name, raw.contains(it)) }
        }
        db.deleteChat("id")
        assertNull(db.summary("id")); assertTrue(db.messages("id").isEmpty()); assertTrue(db.recall("classified garden", "", null).isEmpty())
    }
    @Test fun oldCurrentChatFactsCanBeRecalledWithoutRepeatingLatestTurns() {
        val db = store(); db.upsertChat("a", "Long chat")
        db.append("a", message("old", "My favourite bicycle is cerulean"))
        repeat(20) { db.append("a", message("recent$it", "irrelevant recent turn $it")) }
        val memory = db.context("What colour is my bicycle?", "", "a")
        assertTrue(memory.contains("cerulean")); assertFalse(memory.contains("irrelevant recent turn 19"))
    }
    @Test fun lostKeyKeepsOldArchiveAndAllowsFreshChats() {
        val before = PhoneMemoryStore.recovering(context, crypto)
        stores += before
        before.upsertChat("old", "Kept encrypted")
        before.append("old", message("m", "old protected contents"))
        val oldPath = before.readableDatabase.path
        before.close()
        val kept = mutableListOf<StoreRecovery>()
        val after = PhoneMemoryStore.recovering(context, JvmAesOutboxQueueCrypto(0x33), onRecovered = { kept += it })
        stores += after
        assertEquals(1, kept.size); assertTrue(kept.single().kept)
        assertTrue(File(oldPath).isFile); assertNotEquals(oldPath, after.readableDatabase.path)
        after.upsertChat("fresh", "New chat"); after.append("fresh", message("new", "fresh contents"))
        assertEquals("fresh contents", after.messages("fresh").single().getString("text"))
    }

    @Test fun notesRemainProjectScopedAndCanBeDeleted() {
        val db = store()
        db.upsertNote(JSONObject().put("id", "n1").put("text", "global note"))
        db.upsertNote(JSONObject().put("id", "n2").put("text", "project-a private"), "a")
        assertEquals(1, db.notes("b").size)
        assertEquals(2, db.notes("a").size)
        db.deleteNote("n2"); assertEquals(1, db.notes("a").size)
    }
}
