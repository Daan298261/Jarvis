package com.jarvis.companion

import java.io.File
import java.io.InputStream
import java.security.MessageDigest

/**
 * Loading a GGUF the owner copied onto the phone (no desktop, no internet).
 * A file is only accepted when its SHA-256 matches a model ANZU knows, so a corrupted or swapped
 * file can never be loaded as the offline model.
 */
object ModelSideload {
    val GGUF_MAGIC = byteArrayOf('G'.code.toByte(), 'G'.code.toByte(), 'U'.code.toByte(), 'F'.code.toByte())

    data class Copied(val digest: String, val bytes: Long, val ggufHeader: Boolean)

    fun isGgufHeader(head: ByteArray): Boolean =
        head.size >= GGUF_MAGIC.size && GGUF_MAGIC.indices.all { head[it] == GGUF_MAGIC[it] }

    /** The catalog pack whose pinned SHA-256 (and size, when pinned) matches the copied file. */
    fun match(digest: String, bytes: Long, catalog: List<CompanionPack>): CompanionPack? =
        catalog.firstOrNull { pack ->
            pack.sha256.length == 64 && pack.sha256.equals(digest, ignoreCase = true) &&
                (pack.sizeBytes <= 0L || pack.sizeBytes == bytes)
        }

    /** Streams [input] into [target] while hashing it; returns digest, size and whether it starts with the GGUF magic. */
    fun copyAndHash(input: InputStream, target: File, maxBytes: Long, isCancelled: () -> Boolean = { false }, onBytes: (Long) -> Unit = {}): Copied {
        val digest = MessageDigest.getInstance("SHA-256")
        val head = ByteArray(GGUF_MAGIC.size)
        var headFilled = 0
        var total = 0L
        target.outputStream().use { output ->
            val buffer = ByteArray(1 shl 16)
            while (true) {
                if (isCancelled()) throw kotlinx.coroutines.CancellationException("model import cancelled")
                val read = input.read(buffer)
                if (read < 0) break
                total += read
                if (total > maxBytes) throw IllegalArgumentException(tooLargeCopy(maxBytes))
                if (headFilled < head.size) {
                    val take = minOf(head.size - headFilled, read)
                    System.arraycopy(buffer, 0, head, headFilled, take)
                    headFilled += take
                }
                digest.update(buffer, 0, read)
                output.write(buffer, 0, read)
                onBytes(total)
            }
        }
        return Copied(digest.digest().joinToString("") { "%02x".format(it) }, total, isGgufHeader(head))
    }

    fun notGgufCopy(): String = "That file is not a GGUF model. Pick the .gguf file you downloaded for ANZU."

    fun unknownModelCopy(digest: String): String =
        "That GGUF does not match any model ANZU can verify (SHA-256 ${digest.take(12)}…). Download one of the listed models, then load that file."

    fun tooLargeCopy(maxBytes: Long): String =
        "That file is larger than any model ANZU supports (${maxBytes / (1024 * 1024)} MiB)."

    fun importedCopy(pack: CompanionPack): String = "Verified and loaded ${pack.label}. ANZU can now answer on this phone."
}
