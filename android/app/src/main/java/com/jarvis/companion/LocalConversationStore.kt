package com.jarvis.companion

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Conversations held on this phone (Black Grid mode, RFC-0204 §1.1).
 * They survive app restarts and stay readable with no desktop and no internet.
 * Turns that should reach the desktop also go through [OutboxQueue]; this store is the phone's own history.
 */
class LocalConversationStore(
    context: Context,
    crypto: OutboxQueueCrypto = AndroidKeystoreOutboxQueueCrypto("anzu-local-conversations-v1"),
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val file = EncryptedJsonFile(File(context.noBackupFilesDir, "local-conversations"), crypto)

    /** Newest first; each item has id, title, updated_at, message_count and local=true. */
    fun conversations(): List<JSONObject> {
        val items = file.read().optJSONArray("conversations") ?: JSONArray()
        return items.objects()
            .sortedByDescending { it.optLong("updated_at") }
            .map { conv ->
                JSONObject()
                    .put("id", conv.optString("id"))
                    .put("title", conv.optString("title"))
                    .put("updated_at", conv.optLong("updated_at"))
                    .put("message_count", conv.optJSONArray("messages")?.length() ?: 0)
                    .put("local", true)
            }
    }

    fun messages(id: String): List<JSONObject> =
        find(file.read(), id)?.optJSONArray("messages")?.objects() ?: emptyList()

    fun exists(id: String): Boolean = find(file.read(), id) != null

    /**
     * Starts a conversation titled from its first message and returns its id. [linkedDesktopId] is the
     * desktop conversation it continues, so offline turns sync back into that thread.
     */
    fun create(firstText: String, linkedDesktopId: String? = null): String {
        val id = LOCAL_PREFIX + UUID.randomUUID().toString()
        file.update { root ->
            val items = root.optJSONArray("conversations") ?: JSONArray()
            items.put(
                JSONObject()
                    .put("id", id)
                    .put("title", titleFor(firstText))
                    .put("updated_at", clock())
                    .put("desktop_conversation_id", linkedDesktopId?.takeUnless { isLocal(it) } ?: "")
                    .put("messages", JSONArray()),
            )
            root.put("conversations", trimConversations(items))
        }
        return id
    }

    fun append(id: String, message: JSONObject) {
        file.update { root ->
            val conv = find(root, id) ?: error("Conversation $id is not on this phone")
            val messages = conv.optJSONArray("messages") ?: JSONArray()
            messages.put(JSONObject(message.toString()).put("at", clock()))
            while (messages.length() > MAX_MESSAGES) messages.remove(0)
            conv.put("messages", messages)
            conv.put("updated_at", clock())
        }
    }

    fun linkedDesktopId(id: String): String? =
        find(file.read(), id)?.optString("desktop_conversation_id")?.takeIf { it.isNotBlank() }

    fun linkDesktop(id: String, desktopConversationId: String) {
        file.update { root -> find(root, id)?.put("desktop_conversation_id", desktopConversationId) }
    }

    fun delete(id: String) {
        file.update { root ->
            val items = root.optJSONArray("conversations") ?: JSONArray()
            val kept = JSONArray()
            items.objects().filter { it.optString("id") != id }.forEach { kept.put(it) }
            root.put("conversations", kept)
        }
    }

    private fun find(root: JSONObject, id: String): JSONObject? =
        root.optJSONArray("conversations")?.objects()?.firstOrNull { it.optString("id") == id }

    private fun trimConversations(items: JSONArray): JSONArray {
        if (items.length() <= MAX_CONVERSATIONS) return items
        val kept = JSONArray()
        items.objects().sortedByDescending { it.optLong("updated_at") }.take(MAX_CONVERSATIONS).forEach { kept.put(it) }
        return kept
    }

    companion object {
        const val LOCAL_PREFIX = "local-"
        const val MAX_CONVERSATIONS = 200
        const val MAX_MESSAGES = 500
        const val TITLE_CHARS = 48

        fun isLocal(id: String?): Boolean = id?.startsWith(LOCAL_PREFIX) == true

        fun titleFor(text: String): String {
            val line = text.trim().lineSequence().firstOrNull().orEmpty().replace(Regex("\\s+"), " ")
            if (line.isEmpty()) return "Conversation on this phone"
            return if (line.length <= TITLE_CHARS) line else line.take(TITLE_CHARS - 1).trimEnd() + "…"
        }
    }
}
