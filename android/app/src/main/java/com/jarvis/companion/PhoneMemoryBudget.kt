package com.jarvis.companion

import org.json.JSONArray
import org.json.JSONObject

/** Real-token budget, with owner instructions above recalled data. No embedding runtime or model pass. */
object PhoneMemoryBudget {
    fun fit(raw: String, tokenize: (String) -> Int, limit: Int): String {
        if (raw.isBlank() || limit <= 0) return ""
        val value = JSONObject(raw)
        fun size() = tokenize(value.toString())
        for (field in listOf("historical_quotes", "current_chat_summary")) {
            val rows = value.optJSONArray(field) ?: JSONArray()
            while (rows.length() > 0 && size() > limit) rows.remove(rows.length() - 1)
        }
        for (field in listOf("owner_notes", "owner_instructions")) {
            val text = value.optString(field)
            var low = 0; var high = text.length; var best = ""
            if (size() <= limit) break
            while (low <= high) {
                val mid = (low + high) ushr 1
                value.put(field, text.take(mid))
                if (size() <= limit) { best = text.take(mid); low = mid + 1 } else high = mid - 1
            }
            value.put(field, best)
        }
        return value.toString().takeIf { size() <= limit } ?: ""
    }
}
