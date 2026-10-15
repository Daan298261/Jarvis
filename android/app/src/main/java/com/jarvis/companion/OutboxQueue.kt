package com.jarvis.companion

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Multi-turn offline queue (RFC-0108). Device-local drafts until Leader sync accepts them.
 * Separate from the single online [Outbox] submission journal.
 */
class OutboxQueue(
    context: Context,
    crypto: OutboxQueueCrypto = AndroidKeystoreOutboxQueueCrypto("jarvis-offline-queue-v1"),
    onRecovered: (StoreRecovery) -> Unit = {},
) {
    private val file = EncryptedJsonFile(File(context.noBackupFilesDir, "offline-turn-queue"), crypto, onRecovered = onRecovered)

    fun readAll(): List<JSONObject> {
        val items = file.read().optJSONArray("items") ?: JSONArray()
        return (0 until items.length()).mapNotNull { items.optJSONObject(it) }
    }

    fun pendingCount(): Int = readAll().count { !it.optBoolean("synced", false) }

    fun append(turn: JSONObject) {
        file.update { root ->
            val items = root.optJSONArray("items") ?: JSONArray()
            val copy = JSONObject(turn.toString())
            copy.put("queued_at", System.currentTimeMillis())
            copy.put("synced", false)
            items.put(copy)
            root.put("items", items)
        }
    }

    fun markSynced(clientMessageIds: Collection<String>) {
        if (clientMessageIds.isEmpty()) return
        val wanted = clientMessageIds.toSet()
        file.update { root ->
            val items = root.optJSONArray("items") ?: JSONArray()
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                val id = item.optString("client_message_id").ifBlank { item.optString("request_id") }
                if (wanted.contains(id)) item.put("synced", true)
            }
            root.put("items", items)
        }
    }

    fun pruneSynced() {
        file.update { root ->
            val items = root.optJSONArray("items") ?: JSONArray()
            val kept = JSONArray()
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                if (!item.optBoolean("synced", false)) kept.put(item)
            }
            root.put("items", kept)
        }
    }

    fun forgetConversation(id: String) {
        file.update { root ->
            root.put("items", JSONArray(root.optJSONArray("items")?.objects().orEmpty().filter { it.optString(OfflineSyncPlanner.CONVERSATION_KEY) != id }))
        }
    }

    fun clear() {
        file.delete()
    }
}
