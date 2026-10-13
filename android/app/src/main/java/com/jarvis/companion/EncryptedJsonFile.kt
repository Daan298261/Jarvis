package com.jarvis.companion

import android.util.AtomicFile
import android.util.Log
import org.json.JSONObject
import java.io.File

private const val TAG = "EncryptedJsonFile"

/**
 * One encrypted, atomically replaced JSON document in app-private no-backup storage.
 * Used by the offline queue and the on-phone conversation and note stores so case content never lands in plain text.
 *
 * If the stored bytes can no longer be decrypted or parsed (for example the Keystore key was lost after a
 * restore), the file is moved aside as `<name>.<millis>.corrupt`, [onRecovered] is told, and the store
 * starts empty, instead of failing every later read and write.
 */
class EncryptedJsonFile(
    private val file: File,
    private val crypto: OutboxQueueCrypto,
    private val clock: () -> Long = System::currentTimeMillis,
    private val onRecovered: (File) -> Unit = {},
) {
    private val atomic = AtomicFile(file)
    private val lock = Any()

    fun read(): JSONObject = synchronized(lock) { readUnlocked() }

    fun update(block: (JSONObject) -> Unit): JSONObject = synchronized(lock) {
        val root = readUnlocked()
        block(root)
        writeUnlocked(root)
        root
    }

    fun delete() = synchronized(lock) { atomic.delete() }

    private fun readUnlocked(): JSONObject {
        val bytes = try {
            atomic.openRead().use { it.readBytes() }
        } catch (_: java.io.FileNotFoundException) {
            return JSONObject()
        }
        return try {
            JSONObject(crypto.decrypt(bytes).toString(Charsets.UTF_8))
        } catch (error: Exception) {
            quarantine(error)
            JSONObject()
        }
    }

    private fun quarantine(cause: Exception) {
        val target = corruptFileFor(file, clock())
        Log.e(TAG, "Cannot decrypt ${file.name}; moving it aside as ${target.name}", cause)
        if (file.exists() && !file.renameTo(target)) {
            Log.e(TAG, "Could not move ${file.name} aside; deleting it so ANZU can start fresh")
        }
        atomic.delete() // clears the base file if the move failed, plus any stale backup copy
        onRecovered(target)
    }

    private fun writeUnlocked(value: JSONObject) {
        val bytes = crypto.encrypt(value.toString().toByteArray(Charsets.UTF_8))
        val stream = atomic.startWrite()
        try {
            stream.write(bytes)
            atomic.finishWrite(stream)
        } catch (error: Exception) {
            atomic.failWrite(stream)
            throw error
        }
    }

    companion object {
        fun corruptFileFor(file: File, millis: Long): File = File(file.parentFile, "${file.name}.$millis.corrupt")

        /** Owner-facing notice; [what] is e.g. "conversations". */
        fun recoveryCopy(what: String): String =
            "ANZU could not unlock the $what saved on this phone (this can happen after a restore or a security change), so it started fresh. The unreadable copy was kept on the phone."
    }
}
