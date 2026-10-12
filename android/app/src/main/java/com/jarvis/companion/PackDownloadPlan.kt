package com.jarvis.companion

/**
 * Resume + storage rules for direct Hugging Face pack downloads (RFC-0204 setup).
 * Multi-GB GGUF downloads over mobile networks drop often; the .partial file is kept
 * and continued with an HTTP Range request instead of starting over.
 */
object PackDownloadPlan {
    /** Head-room kept free beyond the pack so Android and the app keep working. */
    const val STORAGE_MARGIN_BYTES = 256L * 1024 * 1024

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
