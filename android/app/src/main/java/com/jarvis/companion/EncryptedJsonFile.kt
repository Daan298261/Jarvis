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
 * restore), the file is moved aside as `<name>.<millis>.corrupt`, [onRecovered] is told whether that
 * copy was really kept, and the store starts empty, instead of failing every later read and write.
 */
class EncryptedJsonFile(
    private val file: File,
    private val crypto: OutboxQueueCrypto,
    private val clock: () -> Long = System::currentTimeMillis,
    private val onRecovered: (StoreRecovery) -> Unit = {},
    private val moveAside: (from: File, to: File) -> Boolean = { from, to -> from.renameTo(to) },
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
        val kept = file.exists() && moveAside(file, target) && target.exists()
        if (!kept) {
            Log.e(TAG, "Could not move ${file.name} aside; deleting it so ANZU can start fresh")
        }
        atomic.delete() // clears the base file if the move failed, plus any stale backup copy
        onRecovered(StoreRecovery(target, kept))
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

        /** Owner-facing notice; [what] is e.g. "conversations", [kept] whether the unreadable copy survived. */
        fun recoveryCopy(what: String, kept: Boolean): String {
            val lead = "ANZU could not unlock the $what saved on this phone (this can happen after a restore or a security change), so it started fresh."
            return if (kept) "$lead The unreadable copy was kept on the phone."
            else "$lead The unreadable copy could not be kept and was removed."
        }
    }
}

/** Outcome of moving an unreadable store aside: [copy] is where it was meant to go, [kept] whether it is really there. */
data class StoreRecovery(val copy: File, val kept: Boolean)
