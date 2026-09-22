package com.jarvis.companion

object MediaUploadPlanner {
    const val CHUNK_SIZE = 2 * 1024 * 1024

    fun detectKind(contentType: String?, name: String): String {
        val type = contentType?.lowercase() ?: ""
        val lower = name.lowercase()
        if (type.startsWith("image/") || lower.matches(Regex(".*\\.(jpe?g|png|webp|heic|gif|bmp)$"))) return "image"
        if (type.startsWith("video/") || lower.matches(Regex(".*\\.(mp4|webm|mov|mkv)$"))) return "video"
        if (type.startsWith("audio/") || lower.matches(Regex(".*\\.(wav|mp3|m4a|ogg|flac)$"))) return "audio"
        return "file"
    }

    fun chunkCount(size: Long): Int = if (size <= 0) 1 else ((size + CHUNK_SIZE - 1) / CHUNK_SIZE).toInt()

    fun shouldChunk(kind: String, size: Long): Boolean = kind == "video" || size > CHUNK_SIZE
}
