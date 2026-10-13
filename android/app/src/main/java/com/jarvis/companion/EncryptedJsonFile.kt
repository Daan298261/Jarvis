package com.jarvis.companion

import android.util.AtomicFile
import org.json.JSONObject
import java.io.File

/**
 * One encrypted, atomically replaced JSON document in app-private no-backup storage.
 * Shared by the on-phone conversation and note stores so case content never lands in plain text.
 */
class EncryptedJsonFile(file: File, private val crypto: OutboxQueueCrypto) {
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
        return JSONObject(crypto.decrypt(bytes).toString(Charsets.UTF_8))
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
}
