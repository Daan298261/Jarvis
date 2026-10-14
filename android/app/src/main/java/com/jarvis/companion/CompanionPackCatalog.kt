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
    /** Default offline pack (RFC-0204 §2.1): minimal-refusal Qwen3.5 2B, fits S20-class phones. */
    const val HERETIC_2B_ID = "qwen3.5-2b-heretic-q4"
    /** Opt-in stronger pack for 12 GB phones; only used when the owner selects it. */
    const val ABLITERATED_4B_ID = "qwen3.5-4b-abliterated-q4"
    const val INSTRUCT_15B_ID = "qwen2.5-1.5b-instruct-q4"
    const val INSTRUCT_3B_ID = "qwen2.5-3b-instruct-q4"

    /** Built-in allowlist; Leader catalog merges by id (URLs/hashes from host). */
    // URLs pin the Hugging Face commit so sha256/size always match the served bytes.
    private const val URL_HERETIC_2B =
        "https://huggingface.co/jordanwoodson/Qwen3.5-2B-heretic-GGUF/resolve/c166d9f30a342a379bbe3299aef938834654e1aa/Qwen3.5-2B-heretic-Q4_K_M.gguf"
    private const val URL_ABLITERATED_4B =
        "https://huggingface.co/mradermacher/Qwen3.5-4B-abliterated-GGUF/resolve/f3b61227dde75c72d12391c443efd6fa0229e0eb/Qwen3.5-4B-abliterated.Q4_K_M.gguf"
    private const val URL_15B =
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    private const val URL_3B =
        "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"

    val builtIn: List<CompanionPack> = listOf(
        CompanionPack(
            id = HERETIC_2B_ID,
            label = "Qwen3.5 2B Heretic — minimal refusals (Q4_K_M)",
            filename = "Qwen3.5-2B-heretic-Q4_K_M.gguf",
            sizeBytes = 1_270_807_936L,
            minRamMb = 2560,
            sha256 = "dad8a69dddcd64f2221dd06ae5c46baceb31ed9bd0dec330306d77762c377cf1",
            url = URL_HERETIC_2B,
            recommended = true,
        ),
        CompanionPack(
            id = ABLITERATED_4B_ID,
            label = "Qwen3.5 4B Abliterated — opt-in, needs ~4.5 GB free RAM (8 GB+ phones) (Q4_K_M)",
            filename = "Qwen3.5-4B-abliterated.Q4_K_M.gguf",
            sizeBytes = 2_707_514_688L,
            minRamMb = 4608,
            sha256 = "1ec0b30c75b49223c82542caf2635a7af4edcda80d8c89759cc000d3871bf48e",
            url = URL_ABLITERATED_4B,
            recommended = false,
        ),
        CompanionPack(
            id = INSTRUCT_15B_ID,
            label = "Qwen2.5 1.5B Instruct (Q4_K_M)",
            filename = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
            sizeBytes = 1_117_320_736L,
            minRamMb = 3072,
            sha256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
            url = URL_15B,
            recommended = false,
        ),
        CompanionPack(
            id = INSTRUCT_3B_ID,
            label = "Qwen2.5 3B Instruct (Q4_K_M)",
            filename = "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            sizeBytes = 2_104_932_768L,
            minRamMb = 5120,
            sha256 = "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d",
            url = URL_3B,
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

    fun isLegalAllowlistRow(pack: CompanionPack): Boolean =
        pack.url.isNotBlank() &&
            pack.sha256.length == 64 &&
            pack.sha256.any { it != '0' } &&
            pack.filename.isNotBlank() &&
            pack.sizeBytes > 0L

    /**
     * Generic abliterated candidate: a legal catalog row that is not one of the
     * two Instruct fallbacks. No unnamed placeholder row is ever synthesized.
     */
    fun isAbliteratedCandidate(pack: CompanionPack): Boolean =
        isLegalAllowlistRow(pack) && pack.id != INSTRUCT_15B_ID && pack.id != INSTRUCT_3B_ID

    /**
     * Offline load order (RFC-0204 §2.1): the owner's selected abliterated pack,
     * else the recommended (default) abliterated pack, else 1.5B Instruct, else the
     * owner's selected 3B Instruct. Opt-in abliterated packs (recommended = false)
     * are never auto-loaded unless selected.
     */
    fun resolveOfflinePack(
        catalog: List<CompanionPack>,
        selectedId: String,
        canLoad: (CompanionPack) -> Boolean,
    ): CompanionPack? {
        catalog.firstOrNull { it.id == selectedId && isAbliteratedCandidate(it) && canLoad(it) }?.let { return it }
        catalog.firstOrNull { it.recommended && isAbliteratedCandidate(it) && canLoad(it) }?.let { return it }
        catalog.firstOrNull { it.id == INSTRUCT_15B_ID && canLoad(it) }?.let { return it }
        if (selectedId == INSTRUCT_3B_ID) {
            catalog.firstOrNull { it.id == INSTRUCT_3B_ID && canLoad(it) }?.let { return it }
        }
        return null
    }
}
