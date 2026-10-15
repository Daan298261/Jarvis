package com.jarvis.companion

import androidx.test.core.app.ApplicationProvider
import org.json.JSONArray
import org.json.JSONObject
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
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** The Keystore key "changed" (e.g. after a restore): a different AES key, so older bytes fail to decrypt. */
private class LostKeyCrypto : OutboxQueueCrypto {
    private val key = SecretKeySpec(ByteArray(32) { 0x33 }, "AES")
    override fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key)
        return cipher.iv + cipher.doFinal(plain)
    }
    override fun decrypt(stored: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, stored.copyOfRange(0, 12)))
        return cipher.doFinal(stored.copyOfRange(12, stored.size))
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33], shadows = [ReplaceAtomicFileShadow::class])
class StoreRecoveryAndSyncTest {
    private val context get() = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val dir get() = context.noBackupFilesDir

    @Before
    fun clean() {
        dir.listFiles()?.forEach { it.delete() }
    }

    @Test
    fun unreadableConversationsAreMovedAsideAndStoreStartsFresh() {
        val good = LocalConversationStore(context, JvmAesOutboxQueueCrypto()) { 1L }
        good.append(good.create("old case chat"), JSONObject().put("role", "user").put("text", "old"))
        val recovered = mutableListOf<File>()
        val broken = LocalConversationStore(context, LostKeyCrypto(), { 42L }) { recovered += it.copy; assertTrue(it.kept) }

        assertTrue(broken.conversations().isEmpty())
        assertEquals(listOf("local-conversations.42.corrupt"), recovered.map { it.name })
        assertTrue(File(dir, "local-conversations.42.corrupt").isFile)
        // Later writes work instead of throwing on every send.
        val id = broken.create("fresh")
        broken.append(id, JSONObject().put("role", "user").put("text", "fresh"))
        assertEquals(listOf("fresh"), broken.messages(id).map { it.getString("text") })
        assertEquals(2, recovered.size)
        assertTrue(recovered.any { it.name == PhoneMemoryStore.DB_NAME && it.isFile })
    }

    @Test
    fun unreadableNotesAndQueueRecoverToo() {
        LocalNotesStore(context, JvmAesOutboxQueueCrypto()).add("gate code")
        OutboxQueue(context, JvmAesOutboxQueueCrypto()).append(JSONObject().put("request_id", "a"))
        val recovered = mutableListOf<String>()
        val notes = LocalNotesStore(context, LostKeyCrypto(), { 7L }) { recovered += it.copy.name }
        val queue = OutboxQueue(context, LostKeyCrypto()) { recovered += it.copy.name }
        assertTrue(notes.notes().isEmpty())
        assertEquals(0, queue.pendingCount())
        assertTrue(recovered.contains("local-notes.7.corrupt"))
        assertTrue(recovered.any { it.startsWith("offline-turn-queue.") && it.endsWith(".corrupt") })
        notes.add("new note")
        assertEquals(listOf("new note"), notes.notes().map { it.getString("text") })
    }

    @Test
    fun garbageBytesAreTreatedAsCorrupt() {
        File(dir, "local-notes").writeBytes(ByteArray(10) { 1 })
        var hit = false
        val notes = LocalNotesStore(context, JvmAesOutboxQueueCrypto()) { hit = true }
        assertTrue(notes.notes().isEmpty())
        assertTrue(hit)
    }

    @Test
    fun missingFileIsNotARecovery() {
        var hit = false
        assertTrue(LocalNotesStore(context, JvmAesOutboxQueueCrypto()) { hit = true }.notes().isEmpty())
        assertFalse(hit)
    }

    @Test
    fun recoveryCopyIsPlain() {
        val copy = EncryptedJsonFile.recoveryCopy("conversations", kept = true)
        assertTrue(copy.contains("started fresh"))
        assertTrue(copy.contains("was kept"))
        assertFalse(copy.contains("Keystore"))
        val lost = EncryptedJsonFile.recoveryCopy("conversations", kept = false)
        assertTrue(lost.contains("could not be kept"))
        assertFalse(lost.contains("was kept"))
    }

    private fun turn(id: String, key: String?) =
        StandaloneActions.userTurnJson(id, "t$id", consequential = false, autoReplay = true, conversationKey = key)

    @Test
    fun turnsCarryTheirConversation() {
        assertEquals("local-a", turn("1", "local-a").getString(OfflineSyncPlanner.CONVERSATION_KEY))
        assertEquals("", turn("1", null).getString(OfflineSyncPlanner.CONVERSATION_KEY))
        assertFalse(OfflineSyncPlanner.wireTurn(turn("1", "local-a")).has(OfflineSyncPlanner.CONVERSATION_KEY))
    }

    @Test
    fun syncIsPlannedPerConversationNotIntoTheOpenOne() {
        val pending = listOf(turn("1", "local-a"), turn("2", "local-b"), turn("3", "local-a"), turn("4", "desk-9"), turn("5", null))
        val linked = mapOf("local-a" to "desk-a")
        val batches = OfflineSyncPlanner.plan(pending) { linked[it] }
        assertEquals(listOf("local-a", "local-b", "desk-9", ""), batches.map { it.conversationKey })
        assertEquals(listOf("desk-a", null, "desk-9", null), batches.map { it.desktopConversationId })
        assertEquals(listOf("1", "3"), batches[0].turns.map { OfflineSyncPlanner.turnId(it) })
    }

    @Test
    fun largeConversationsAreSplitToTheServerLimit() {
        val pending = (1..120).map { turn(it.toString(), "local-a") }
        val batches = OfflineSyncPlanner.plan(pending) { null }
        assertEquals(listOf(50, 50, 20), batches.map { it.turns.size })
        assertTrue(batches.all { it.conversationKey == "local-a" })
        assertNull(batches[0].desktopConversationId)
    }

    @Test
    fun failedMoveAsideReportsTheCopyWasNotKept() {
        val target = File(dir, "probe")
        EncryptedJsonFile(target, JvmAesOutboxQueueCrypto()).update { it.put("x", 1) }
        val outcomes = mutableListOf<StoreRecovery>()
        val broken = EncryptedJsonFile(target, LostKeyCrypto(), { 9L }, { outcomes += it }, moveAside = { _, _ -> false })
        assertEquals(0, broken.read().length())
        assertEquals(1, outcomes.size)
        assertFalse(outcomes[0].kept)
        assertFalse(File(dir, "probe.9.corrupt").exists())
        assertFalse(target.exists())
        // Store still works after the failed move.
        broken.update { it.put("y", 2) }
        assertEquals(2, broken.read().getInt("y"))
    }

    /** Mirrors backend sync_offline_turns: creates a thread for a client-supplied id, dedupes per thread by turn id. */
    private class FakeDesktop {
        val threads = LinkedHashMap<String, MutableList<String>>()
        var loseNextReply = false
        fun post(conversationId: String, turns: JSONArray) {
            val stored = threads.getOrPut(conversationId) { mutableListOf() }
            for (i in 0 until turns.length()) {
                val id = OfflineSyncPlanner.turnId(turns.getJSONObject(i))
                if (id !in stored) stored += id
            }
            if (loseNextReply) { loseNextReply = false; throw java.io.IOException("reply lost") }
        }
    }

    private fun prefs() = context.getSharedPreferences("sync-test", android.content.Context.MODE_PRIVATE).also { it.edit().clear().commit() }

    @Test
    fun lostReplyThenNewTurnRetriesIntoTheSameThread() {
        val prefs = prefs()
        val conversations = LocalConversationStore(context, JvmAesOutboxQueueCrypto())
        val chat = conversations.create("offline chat")
        val desktop = FakeDesktop()
        val queue = mutableListOf(turn("1", chat), turn("2", chat))
        val delivered = mutableSetOf<String>()
        fun runSync(ids: DesktopThreadIds) = OfflineSyncPlanner.syncAll(
            queue.filter { OfflineSyncPlanner.turnId(it) !in delivered }, ids,
            post = desktop::post, synced = { delivered += it },
        )

        desktop.loseNextReply = true
        runCatching { runSync(PhoneDesktopThreadIds(prefs, conversations)) }
        assertTrue(delivered.isEmpty())
        val linked = LocalConversationStore(context, JvmAesOutboxQueueCrypto()).linkedDesktopId(chat)
        assertEquals(listOf(linked), desktop.threads.keys.toList())

        queue += turn("3", chat)
        // Fresh instances: the thread id must come from storage, not memory.
        runSync(PhoneDesktopThreadIds(prefs, LocalConversationStore(context, JvmAesOutboxQueueCrypto())))
        assertEquals(1, desktop.threads.size)
        assertEquals(listOf("1", "2", "3"), desktop.threads.getValue(linked!!))
        assertEquals(setOf("1", "2", "3"), delivered)
    }

    @Test
    fun turnsWithoutAConversationStayInOneThreadAcrossAFailedBatch() {
        val prefs = prefs()
        val conversations = LocalConversationStore(context, JvmAesOutboxQueueCrypto())
        val queue = (1..60).map { turn(it.toString(), null) }
        val delivered = mutableSetOf<String>()
        val desktop = FakeDesktop()
        var calls = 0
        fun runSync() = OfflineSyncPlanner.syncAll(
            queue.filter { OfflineSyncPlanner.turnId(it) !in delivered }, PhoneDesktopThreadIds(prefs, conversations),
            post = { id, turns -> calls++; if (calls == 2) throw java.io.IOException("offline again"); desktop.post(id, turns) },
            synced = { delivered += it },
        )
        runCatching { runSync() }
        assertEquals(50, delivered.size)
        runSync()
        assertEquals(1, desktop.threads.size)
        assertEquals((1..60).map { it.toString() }, desktop.threads.values.single())
    }

    @Test
    fun deletedPhoneConversationStillGetsAStableThread() {
        val prefs = prefs()
        val conversations = LocalConversationStore(context, JvmAesOutboxQueueCrypto())
        val ids = PhoneDesktopThreadIds(prefs, conversations)
        val batch = OfflineSyncBatch("local-gone", null, listOf(turn("1", "local-gone")))
        val first = OfflineSyncPlanner.threadFor(batch, ids)
        assertEquals(first, OfflineSyncPlanner.threadFor(batch, PhoneDesktopThreadIds(prefs, conversations)))
    }
}
