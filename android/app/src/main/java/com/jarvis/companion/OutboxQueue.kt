package com.jarvis.companion

import android.content.Context
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Multi-turn offline queue (RFC-0108). Device-local drafts until Leader sync accepts them.
 * Separate from the single online [Outbox] submission journal.
 */
class OutboxQueue(
    context: Context,
    private val crypto: OutboxQueueCrypto = AndroidKeystoreOutboxQueueCrypto("jarvis-offline-queue-v1"),
) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "offline-turn-queue"))

    fun readAll(): List<JSONObject> {
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        return (0 until items.length()).mapNotNull { items.optJSONObject(it) }
    }

    fun pendingCount(): Int = readAll().count { !it.optBoolean("synced", false) }

    fun append(turn: JSONObject) {
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        val copy = JSONObject(turn.toString())
        copy.put("queued_at", System.currentTimeMillis())
        copy.put("synced", false)
        items.put(copy)
        root.put("items", items)
        writeRoot(root)
    }

    fun markSynced(clientMessageIds: Collection<String>) {
        if (clientMessageIds.isEmpty()) return
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        val wanted = clientMessageIds.toSet()
        for (index in 0 until items.length()) {
            val item = items.optJSONObject(index) ?: continue
            val id = item.optString("client_message_id").ifBlank { item.optString("request_id") }
            if (wanted.contains(id)) item.put("synced", true)
        }
        root.put("items", items)
        writeRoot(root)
    }

    fun pruneSynced() {
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        val kept = JSONArray()
        for (index in 0 until items.length()) {
            val item = items.optJSONObject(index) ?: continue
            if (!item.optBoolean("synced", false)) kept.put(item)
        }
        root.put("items", kept)
        writeRoot(root)
    }

    fun clear() {
        file.delete()
    }

    private fun readRoot(): JSONObject {
        val bytes = try {
            file.openRead().use { it.readBytes() }
        } catch (_: java.io.FileNotFoundException) {
            return JSONObject().put("items", JSONArray())
        }
        return JSONObject(crypto.decrypt(bytes).toString(Charsets.UTF_8))
    }

    private fun writeRoot(value: JSONObject) {
        val bytes = crypto.encrypt(value.toString().toByteArray())
        val stream = file.startWrite()
        try {
            stream.write(bytes)
            file.finishWrite(stream)
        } catch (error: Exception) {
            file.failWrite(stream)
            throw error
        }
    }
}
