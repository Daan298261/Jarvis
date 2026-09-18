package com.jarvis.companion

import org.json.JSONArray
import org.json.JSONObject

data class CompanionPack(
    val id: String,
    val label: String,
    val filename: String,
    val sizeBytes: Long,
    val minRamMb: Int,
    val sha256: String,
    val url: String,
    val recommended: Boolean,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("label", label)
        .put("filename", filename)
        .put("size_bytes", sizeBytes)
        .put("min_ram_mb", minRamMb)
        .put("sha256", sha256)
        .put("url", url)
        .put("recommended", recommended)
}

object CompanionPackCatalog {
    /** Built-in allowlist; Leader catalog merges by id (URLs/hashes from host). */
    val builtIn: List<CompanionPack> = listOf(
        CompanionPack(
            id = "qwen2.5-1.5b-instruct-q4",
            label = "Qwen2.5 1.5B Instruct (Q4_K_M)",
            filename = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
            sizeBytes = 1_050_000_000L,
            minRamMb = 3072,
            sha256 = "",
            url = "",
            recommended = true,
        ),
        CompanionPack(
            id = "qwen2.5-3b-instruct-q4",
            label = "Qwen2.5 3B Instruct (Q4_K_M)",
            filename = "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            sizeBytes = 2_100_000_000L,
            minRamMb = 5120,
            sha256 = "",
            url = "",
            recommended = false,
        ),
    )

    fun merge(leader: JSONObject?): List<CompanionPack> {
        val remote = leader?.optJSONArray("packs") ?: JSONArray()
        val byId = builtIn.associateBy { it.id }.toMutableMap()
        for (index in 0 until remote.length()) {
            val item = remote.optJSONObject(index) ?: continue
            val id = item.optString("id")
            val base = byId[id] ?: CompanionPack(
                id = id,
                label = item.optString("label", id),
                filename = item.optString("filename"),
                sizeBytes = item.optLong("size_bytes"),
                minRamMb = item.optInt("min_ram_mb", 4096),
                sha256 = item.optString("sha256"),
                url = item.optString("url"),
                recommended = item.optBoolean("recommended"),
            )
            byId[id] = base.copy(
                label = item.optString("label", base.label),
                filename = item.optString("filename", base.filename),
                sizeBytes = item.optLong("size_bytes", base.sizeBytes),
                minRamMb = item.optInt("min_ram_mb", base.minRamMb),
                sha256 = item.optString("sha256", base.sha256),
                url = item.optString("url", base.url),
                recommended = item.optBoolean("recommended", base.recommended),
            )
        }
        return byId.values.sortedByDescending { it.recommended }
    }
}
