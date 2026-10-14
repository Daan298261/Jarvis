package com.jarvis.companion

/**
 * Resume + storage rules for direct Hugging Face pack downloads (RFC-0204 setup).
 * Multi-GB GGUF downloads over mobile networks drop often; the .partial file is kept
 * and continued with an HTTP Range request instead of starting over.
 */
object PackDownloadPlan {
    /**
     * Moves a verified download over the installed file in one step. Unlike File.renameTo, the result is
     * checked and an existing target is replaced, so the old copy survives unless the new one is in place.
     */
    fun replaceWithVerified(partial: java.io.File, target: java.io.File) {
        try {
            java.nio.file.Files.move(partial.toPath(), target.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING,
                java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        } catch (_: java.nio.file.AtomicMoveNotSupportedException) {
            java.nio.file.Files.move(partial.toPath(), target.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        }
    }

    /** True when [name] is a plain entry directly inside [dir] (no separators, `.`/`..`, or escapes). */
    fun isDirectChild(dir: java.io.File, name: String): Boolean {
        if (name.isEmpty() || name == "." || name == ".." || '/' in name || '\\' in name) return false
        return java.io.File(dir, name).canonicalFile.parentFile == dir.canonicalFile
    }

    /** Head-room kept free beyond the pack so Android and the app keep working. */
    const val STORAGE_MARGIN_BYTES = 256L * 1024 * 1024

    /** Download attempts per tap; each retry resumes the .partial (2 s doubling to 30 s, jittered). */
    const val DOWNLOAD_ATTEMPTS = 6
    const val RETRY_BASE_DELAY_MS = 2_000L
    const val RETRY_MAX_DELAY_MS = 30_000L

    /** Byte offset to resume from, or 0 to start fresh. */
    fun resumeFrom(partialLength: Long, expectedSize: Long): Long = when {
        partialLength <= 0L -> 0L
        expectedSize > 0L && partialLength >= expectedSize -> 0L
        else -> partialLength
    }

    /** A partial at (or past) the expected size only needs verification, not more bytes. */
    fun partialIsComplete(partialLength: Long, expectedSize: Long): Boolean =
        expectedSize > 0L && partialLength == expectedSize

    fun requiredFreeBytes(expectedSize: Long, resumeFrom: Long): Long =
        (expectedSize - resumeFrom).coerceAtLeast(0L) + STORAGE_MARGIN_BYTES

    fun storageBlockReason(freeBytes: Long, expectedSize: Long, resumeFrom: Long): String? {
        val need = requiredFreeBytes(expectedSize, resumeFrom)
        if (freeBytes >= need) return null
        val needMb = need / (1024 * 1024)
        val haveMb = freeBytes / (1024 * 1024)
        return "Not enough storage for this model: need about $needMb MB free, have $haveMb MB. Free up space or pick a smaller pack."
    }

    /** True when the server honoured the Range request, so bytes are appended. */
    fun appendToPartial(resumeFrom: Long, httpCode: Int): Boolean = resumeFrom > 0L && httpCode == 206
}
