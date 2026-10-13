package com.jarvis.companion

import androidx.test.core.app.ApplicationProvider
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
        val broken = LocalConversationStore(context, LostKeyCrypto(), { 42L }) { recovered += it }

        assertTrue(broken.conversations().isEmpty())
        assertEquals(listOf("local-conversations.42.corrupt"), recovered.map { it.name })
        assertTrue(File(dir, "local-conversations.42.corrupt").isFile)
        // Later writes work instead of throwing on every send.
        val id = broken.create("fresh")
        broken.append(id, JSONObject().put("role", "user").put("text", "fresh"))
        assertEquals(listOf("fresh"), broken.messages(id).map { it.getString("text") })
        assertEquals(1, recovered.size)
    }

    @Test
    fun unreadableNotesAndQueueRecoverToo() {
        LocalNotesStore(context, JvmAesOutboxQueueCrypto()).add("gate code")
        OutboxQueue(context, JvmAesOutboxQueueCrypto()).append(JSONObject().put("request_id", "a"))
        val recovered = mutableListOf<String>()
        val notes = LocalNotesStore(context, LostKeyCrypto(), { 7L }) { recovered += it.name }
        val queue = OutboxQueue(context, LostKeyCrypto()) { recovered += it.name }
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
        val copy = EncryptedJsonFile.recoveryCopy("conversations")
        assertTrue(copy.contains("started fresh"))
        assertFalse(copy.contains("Keystore"))
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
}
