package com.jarvis.companion

import android.content.Context
import org.json.JSONObject

/**
 * Persists in-flight chunked upload state for retry (RFC-0109).
 */
class UploadOutbox(context: Context) {
    private val prefs = context.getSharedPreferences("jarvis-upload-outbox", Context.MODE_PRIVATE)

    fun save(payload: JSONObject) {
        prefs.edit().putString("pending", payload.toString()).apply()
    }

    fun read(): JSONObject? {
        val raw = prefs.getString("pending", null) ?: return null
        return runCatching { JSONObject(raw) }.getOrNull()
    }

    fun clear() {
        prefs.edit().remove("pending").apply()
    }
}
