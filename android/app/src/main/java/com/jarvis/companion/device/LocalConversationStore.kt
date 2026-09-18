package com.jarvis.companion.device

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Persists offline chat turns for display until Leader sync (RFC-0108). */
class LocalConversationStore(context: Context) {
    private val file = File(context.noBackupFilesDir, "offline-conversation.json")

    fun readMessages(): List<JSONObject> {
        if (!file.isFile) return emptyList()
        val array = runCatching { JSONObject(file.readText()).optJSONArray("messages") }.getOrNull() ?: return emptyList()
        return (0 until array.length()).mapNotNull { array.optJSONObject(it) }
    }

    fun append(role: String, text: String, requestId: String, offlineLocal: Boolean = true) {
        val messages = readMessages().toMutableList()
        messages.add(
            JSONObject()
                .put("role", role)
                .put("text", text)
                .put("request_id", requestId)
                .put("offline_local", offlineLocal)
                .put("created_at", System.currentTimeMillis()),
        )
        write(messages)
    }

    fun clear() {
        file.delete()
    }

    private fun write(messages: List<JSONObject>) {
        val array = JSONArray()
        messages.forEach { array.put(it) }
        file.parentFile?.mkdirs()
        file.writeText(JSONObject().put("messages", array).toString())
    }
}
