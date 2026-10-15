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
    onRecovered: (StoreRecovery) -> Unit = {},
) {
    private val memoryDelegate = lazy {
        PhoneMemoryStore.recovering(context, crypto, clock, onRecovered).also { it.migrateLegacy(file.read()) }
    }
    val memory: PhoneMemoryStore get() = memoryDelegate.value
    fun close() { if (memoryDelegate.isInitialized()) memoryDelegate.value.close() }
    private val file = EncryptedJsonFile(File(context.noBackupFilesDir, "local-conversations"), crypto, clock, onRecovered)

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
        memory.upsertChat(id, titleFor(firstText), desktopId = linkedDesktopId.orEmpty())
        return id
    }

    fun append(id: String, message: JSONObject) {
        val archived = JSONObject(message.toString()).put("at", clock())
        if (archived.optString("id").isBlank()) archived.put("id", "local-message-" + UUID.randomUUID().toString())
        memory.upsertChat(id, titleFor(message.optString("text")))
        memory.append(id, archived)
        file.update { root ->
            val conv = find(root, id) ?: error("Conversation $id is not on this phone")
            val messages = conv.optJSONArray("messages") ?: JSONArray()
            messages.put(JSONObject(archived.toString()))
            while (messages.length() > MAX_MESSAGES) messages.remove(0)
            conv.put("messages", messages)
            conv.put("updated_at", clock())
        }
    }

    fun linkedDesktopId(id: String): String? =
        find(file.read(), id)?.optString("desktop_conversation_id")?.takeIf { it.isNotBlank() }

    /** Returns false when [id] is not (or no longer) on this phone. */
    fun linkDesktop(id: String, desktopConversationId: String): Boolean {
        var linked = false
        file.update { root -> find(root, id)?.let { it.put("desktop_conversation_id", desktopConversationId); linked = true } }
        if (linked) memory.linkDesktop(id, desktopConversationId)
        return linked
    }

    fun delete(id: String) {
        memory.deleteChat(id)
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
