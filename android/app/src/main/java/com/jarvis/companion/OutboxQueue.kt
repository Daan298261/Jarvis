package com.jarvis.companion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Multi-turn offline queue (RFC-0108). Device-local drafts until Leader sync accepts them.
 * Separate from the single online [Outbox] submission journal.
 */
class OutboxQueue(context: Context) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "offline-turn-queue"))
    private val alias = "jarvis-offline-queue-v1"
    private val keys = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun key(): SecretKey {
        if (!keys.containsAlias(alias)) {
            KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(
                    KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .build(),
                )
            }.generateKey()
        }
        return keys.getKey(alias, null) as SecretKey
    }

    fun readAll(): List<JSONObject> {
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        return (0 until items.length()).mapNotNull { items.optJSONObject(it) }
    }

    fun pendingCount(): Int = readAll().count { !it.optBoolean("synced", false) }

    fun append(turn: JSONObject) {
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        val copy = JSONObject(turn.toString())
        copy.put("queued_at", System.currentTimeMillis())
        copy.put("synced", false)
        items.put(copy)
        root.put("items", items)
        writeRoot(root)
    }

    fun markSynced(clientMessageIds: Collection<String>) {
        if (clientMessageIds.isEmpty()) return
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        val wanted = clientMessageIds.toSet()
        for (index in 0 until items.length()) {
            val item = items.optJSONObject(index) ?: continue
            val id = item.optString("client_message_id").ifBlank { item.optString("request_id") }
            if (wanted.contains(id)) item.put("synced", true)
        }
        root.put("items", items)
        writeRoot(root)
    }

    fun pruneSynced() {
        val root = readRoot()
        val items = root.optJSONArray("items") ?: JSONArray()
        val kept = JSONArray()
        for (index in 0 until items.length()) {
            val item = items.optJSONObject(index) ?: continue
            if (!item.optBoolean("synced", false)) kept.put(item)
        }
        root.put("items", kept)
        writeRoot(root)
    }

    fun clear() {
        file.delete()
    }

    private fun readRoot(): JSONObject {
        val bytes = try {
            file.openRead().use { it.readBytes() }
        } catch (_: java.io.FileNotFoundException) {
            return JSONObject().put("items", JSONArray())
        }
        require(bytes.size >= 28) { "Offline queue is damaged" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        return JSONObject(cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8))
    }

    private fun writeRoot(value: JSONObject) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val bytes = cipher.iv + cipher.doFinal(value.toString().toByteArray())
        val stream = file.startWrite()
        try {
            stream.write(bytes)
            file.finishWrite(stream)
        } catch (error: Exception) {
            file.failWrite(stream)
            throw error
        }
    }
}
