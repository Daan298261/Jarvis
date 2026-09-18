package com.jarvis.companion.device

/** Pinned allowlist — weights are never shipped in the APK (RFC-0108). */
object DeviceModelPackCatalog {
    val packs: List<DeviceModelPackDescriptor> = listOf(
        DeviceModelPackDescriptor(
            id = "qwen2.5-1.5b-instruct-q4",
            label = "Qwen2.5 1.5B Instruct (Q4)",
            filename = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
            downloadUrl = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
            expectedBytes = 1_100_000_000L,
        ),
    )

    val defaultPack: DeviceModelPackDescriptor = packs.first()

    fun find(id: String): DeviceModelPackDescriptor? = packs.firstOrNull { it.id == id }
}
