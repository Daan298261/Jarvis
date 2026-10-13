package com.jarvis.companion

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/** Notes saved on this phone ("remember this", "take a note") while ANZU runs without the desktop. */
class LocalNotesStore(
    context: Context,
    crypto: OutboxQueueCrypto = AndroidKeystoreOutboxQueueCrypto("anzu-local-notes-v1"),
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val file = EncryptedJsonFile(File(context.noBackupFilesDir, "local-notes"), crypto)

    /** Newest first; each item has id, text and created_at. */
    fun notes(): List<JSONObject> =
        (file.read().optJSONArray("notes") ?: JSONArray()).objects().sortedByDescending { it.optLong("created_at") }

    fun add(text: String): JSONObject {
        val body = text.trim()
        require(body.isNotEmpty()) { "Note is empty" }
        val note = JSONObject()
            .put("id", UUID.randomUUID().toString())
            .put("text", body.take(MAX_NOTE_CHARS))
            .put("created_at", clock())
        file.update { root ->
            val items = root.optJSONArray("notes") ?: JSONArray()
            items.put(note)
            root.put("notes", items)
        }
        return note
    }

    fun delete(id: String) {
        file.update { root ->
            val kept = JSONArray()
            (root.optJSONArray("notes") ?: JSONArray()).objects().filter { it.optString("id") != id }.forEach { kept.put(it) }
            root.put("notes", kept)
        }
    }

    companion object {
        const val MAX_NOTE_CHARS = 8000
    }
}
