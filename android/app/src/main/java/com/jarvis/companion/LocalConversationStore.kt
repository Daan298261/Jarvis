package com.jarvis.companion

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.util.UUID

/** SQLite is authoritative; only the recent UI page is bounded. The old encrypted file is preserved. */
class LocalConversationStore(
    context: Context,
    crypto: OutboxQueueCrypto = AndroidKeystoreOutboxQueueCrypto("anzu-local-conversations-v1"),
    private val clock: () -> Long = System::currentTimeMillis,
    onRecovered: (StoreRecovery) -> Unit = {},
) {
    private val memoryDelegate = lazy {
        val db = PhoneMemoryStore.recovering(context, crypto, clock, onRecovered)
        val prefs = context.getSharedPreferences("phone_memory_storage", Context.MODE_PRIVATE)
        if (!db.legacyImported()) {
            val source = if (prefs.getBoolean("legacy_imported", false)) JSONObject() else
                EncryptedJsonFile(File(context.noBackupFilesDir, "local-conversations"), crypto, clock, onRecovered).read()
            db.migrateLegacy(source)
        }
        check(prefs.edit().putBoolean("legacy_imported", true).commit()) { "Cannot save chat migration checkpoint" }
        db
    }
    val memory: PhoneMemoryStore get() = memoryDelegate.value
    fun close() { if (memoryDelegate.isInitialized()) memoryDelegate.value.close() }
    fun conversations(): List<JSONObject> = memory.localChats(MAX_CONVERSATIONS)
    fun messages(id: String): List<JSONObject> = memory.recentMessages(id, MAX_MESSAGES)
    fun exists(id: String): Boolean = memory.chat(id) != null
    fun create(firstText: String, linkedDesktopId: String? = null): String {
        val id = LOCAL_PREFIX + UUID.randomUUID().toString()
        memory.upsertChat(id, titleFor(firstText), desktopId = linkedDesktopId?.takeUnless { isLocal(it) }.orEmpty())
        return id
    }
    fun append(id: String, message: JSONObject) {
        check(memory.chat(id) != null) { "Conversation $id is not on this phone" }
        val archived = JSONObject(message.toString()).put("at", clock())
        if (archived.optString("id").isBlank()) archived.put("id", "local-message-" + UUID.randomUUID().toString())
        memory.append(id, archived)
    }
    fun linkedDesktopId(id: String): String? = memory.chat(id)?.optString("desktop_conversation_id")?.takeIf { it.isNotBlank() }
    fun linkDesktop(id: String, desktopConversationId: String): Boolean {
        if (!exists(id)) return false
        memory.linkDesktop(id, desktopConversationId)
        return true
    }
    fun delete(id: String) { memory.deleteChat(id) }

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
