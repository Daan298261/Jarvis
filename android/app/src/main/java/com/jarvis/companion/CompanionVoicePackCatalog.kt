package com.jarvis.companion

import org.json.JSONArray
import org.json.JSONObject

data class CompanionVoiceArtifact(
    val filename: String,
    val url: String,
    val sha256: String,
    val sizeBytes: Long,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("filename", filename)
        .put("url", url)
        .put("sha256", sha256)
        .put("size_bytes", sizeBytes)
}

data class CompanionVoicePack(
    val id: String,
    val role: String,
    val label: String,
    val engine: String,
    val filename: String,
    val sizeBytes: Long,
    val minRamMb: Int,
    val sha256: String,
    val url: String,
    val recommended: Boolean,
    val artifacts: List<CompanionVoiceArtifact>,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("role", role)
        .put("label", label)
        .put("engine", engine)
        .put("filename", filename)
        .put("size_bytes", sizeBytes)
        .put("min_ram_mb", minRamMb)
        .put("sha256", sha256)
        .put("url", url)
        .put("recommended", recommended)
        .put("artifacts", JSONArray().also { arr -> artifacts.forEach { arr.put(it.toJson()) } })
}

object CompanionVoicePackCatalog {
    private const val URL_WHISPER_TINY =
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin"
    private const val URL_WHISPER_BASE =
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
    private const val URL_PIPER_ONNX =
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
    private const val URL_PIPER_JSON =
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
    private const val POCKET_BASE =
        "https://huggingface.co/soniqo/Pocket-TTS-100M-ONNX-INT8/resolve/v1.0.0"

    val builtIn: List<CompanionVoicePack> = listOf(
        CompanionVoicePack(
            id = "whisper-tiny-en-cpp",
            role = "stt",
            label = "Whisper tiny.en (whisper.cpp)",
            engine = "whisper.cpp",
            filename = "ggml-tiny.en.bin",
            sizeBytes = 77_704_715L,
            minRamMb = 512,
            sha256 = "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
            url = URL_WHISPER_TINY,
            recommended = true,
            artifacts = listOf(
                CompanionVoiceArtifact("ggml-tiny.en.bin", URL_WHISPER_TINY,
                    "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f", 77_704_715L),
            ),
        ),
        CompanionVoicePack(
            id = "whisper-base-en-cpp",
            role = "stt",
            label = "Whisper base.en (whisper.cpp)",
            engine = "whisper.cpp",
            filename = "ggml-base.en.bin",
            sizeBytes = 147_964_211L,
            minRamMb = 1024,
            sha256 = "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002",
            url = URL_WHISPER_BASE,
            recommended = false,
            artifacts = listOf(
                CompanionVoiceArtifact("ggml-base.en.bin", URL_WHISPER_BASE,
                    "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002", 147_964_211L),
            ),
        ),
        CompanionVoicePack(
            id = "pocket-tts-en",
            role = "tts",
            label = "Pocket TTS English (ONNX INT8 / Alba)",
            engine = "pocket-tts-onnx",
            filename = "pocket-tts-en",
            sizeBytes = 126_155_593L,
            minRamMb = 768,
            sha256 = "1e50e05031f8711ab0cb10aac0953432c604104e76180ec4b6f7cc4393746e08",
            url = "$POCKET_BASE/lm_main.int8.onnx",
            recommended = true,
            artifacts = listOf(
                CompanionVoiceArtifact("decoder.int8.onnx", "$POCKET_BASE/decoder.int8.onnx",
                    "ed8d050fc5da275cfca88224b7d2cc29fde7c23e133618f346e98ac505b3d862", 22_695_710L),
                CompanionVoiceArtifact("encoder.onnx", "$POCKET_BASE/encoder.onnx",
                    "2194513df47271ece9f8d2d571facd57b24d96a1d912fdc13bf0e10c69318e85", 512_407L),
                CompanionVoiceArtifact("lm_flow.int8.onnx", "$POCKET_BASE/lm_flow.int8.onnx",
                    "8d627d235c44a597da908e1085ebe241cbbe358964c502c5a5063d18851a5529", 9_962_530L),
                CompanionVoiceArtifact("lm_main.int8.onnx", "$POCKET_BASE/lm_main.int8.onnx",
                    "bfc0c7e7e3d72864fa3bb2ee499f62f21ddc1474b885f5f3ca570f8be73e787e", 76_341_079L),
                CompanionVoiceArtifact("manifest.json", "$POCKET_BASE/manifest.json",
                    "5eeff5278cfb1e9b627d972512ddf1e2dfacf61827103d9fb9c53707b38d0968", 2_934L),
                CompanionVoiceArtifact("text_conditioner.onnx", "$POCKET_BASE/text_conditioner.onnx",
                    "5217b8474621af91127cfef891714337ae8cba106710ce04a426ec4bd56bbd1e", 16_388_498L),
                CompanionVoiceArtifact("token_scores.json", "$POCKET_BASE/token_scores.json",
                    "3baa6ef7d57bac245271e33f96161f3ac60038d753f13f3fdbe24a7d2422ad6b", 123_617L),
                CompanionVoiceArtifact("tokenizer.model", "$POCKET_BASE/tokenizer.model",
                    "d461765ae179566678c93091c5fa6f2984c31bbe990bf1aa62d92c64d91bc3f6", 59_339L),
                CompanionVoiceArtifact("vocab.json", "$POCKET_BASE/vocab.json",
                    "a2673c232cf49dd6eb1ad850e7c7682f6443c2ab64040d1150e9d8f2a7e3587b", 69_479L),
            ),
        ),
        CompanionVoicePack(
            id = "piper-en-lessac-medium",
            role = "tts",
            label = "Piper en_US lessac medium",
            engine = "piper-onnx",
            filename = "en_US-lessac-medium.onnx",
            sizeBytes = 63_206_179L,
            minRamMb = 384,
            sha256 = "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
            url = URL_PIPER_ONNX,
            recommended = false,
            artifacts = listOf(
                CompanionVoiceArtifact("en_US-lessac-medium.onnx", URL_PIPER_ONNX,
                    "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f", 63_201_294L),
                CompanionVoiceArtifact("en_US-lessac-medium.onnx.json", URL_PIPER_JSON,
                    "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0", 4_885L),
            ),
        ),
    )

    fun validateBuiltIn() {
        builtIn.forEach { pack ->
            require(pack.url.isNotBlank()) { "Voice pack ${pack.id} has empty url" }
            require(pack.sha256.length == 64 && pack.sha256.any { it != '0' }) {
                "Voice pack ${pack.id} missing real sha256"
            }
            pack.artifacts.forEach { art ->
                require(art.url.isNotBlank()) { "Voice pack ${pack.id} artifact ${art.filename} has empty url" }
                require(art.sha256.length == 64) { "Voice pack ${pack.id} artifact ${art.filename} bad sha256" }
            }
        }
    }

    fun merge(leader: JSONObject?): List<CompanionVoicePack> {
        val remote = leader?.optJSONArray("packs") ?: JSONArray()
        val byId = builtIn.associateBy { it.id }.toMutableMap()
        for (index in 0 until remote.length()) {
            val item = remote.optJSONObject(index) ?: continue
            val id = item.optString("id")
            if (id.isBlank()) continue
            val base = byId[id]
            val artsRemote = item.optJSONArray("artifacts")
            val artifacts = if (artsRemote != null && artsRemote.length() > 0) {
                (0 until artsRemote.length()).mapNotNull { i ->
                    val a = artsRemote.optJSONObject(i) ?: return@mapNotNull null
                    CompanionVoiceArtifact(
                        filename = a.optString("filename"),
                        url = a.optString("url"),
                        sha256 = a.optString("sha256"),
                        sizeBytes = a.optLong("size_bytes"),
                    )
                }
            } else base?.artifacts ?: emptyList()
            byId[id] = CompanionVoicePack(
                id = id,
                role = item.optString("role", base?.role ?: "stt"),
                label = item.optString("label", base?.label ?: id),
                engine = item.optString("engine", base?.engine ?: ""),
                filename = item.optString("filename", base?.filename ?: ""),
                sizeBytes = item.optLong("size_bytes", base?.sizeBytes ?: 0L),
                minRamMb = item.optInt("min_ram_mb", base?.minRamMb ?: 512),
                sha256 = item.optString("sha256", base?.sha256 ?: ""),
                url = item.optString("url", base?.url ?: ""),
                recommended = item.optBoolean("recommended", base?.recommended ?: false),
                artifacts = artifacts.ifEmpty {
                    listOf(
                        CompanionVoiceArtifact(
                            item.optString("filename", base?.filename ?: ""),
                            item.optString("url", base?.url ?: ""),
                            item.optString("sha256", base?.sha256 ?: ""),
                            item.optLong("size_bytes", base?.sizeBytes ?: 0L),
                        ),
                    )
                },
            )
        }
        return byId.values.sortedWith(compareByDescending<CompanionVoicePack> { it.recommended }.thenBy { it.role })
    }
}
