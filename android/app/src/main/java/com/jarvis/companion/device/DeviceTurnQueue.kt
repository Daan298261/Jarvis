package com.jarvis.companion.device

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

/** Queued offline turns for Leader sync when the session returns (RFC-0108). */
class DeviceTurnQueue(context: Context) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "device-turn-queue"))
    private val alias = "jarvis-device-turn-queue-v1"
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
        val root = readRoot() ?: return emptyList()
        val items = root.optJSONArray("items") ?: return emptyList()
        return (0 until items.length()).mapNotNull { items.optJSONObject(it) }
    }

    fun enqueue(turn: JSONObject) {
        val root = readRoot() ?: JSONObject().put("items", JSONArray())
        val items = root.optJSONArray("items") ?: JSONArray()
        items.put(turn)
        root.put("items", items)
        writeRoot(root)
    }

    fun replaceAll(turns: List<JSONObject>) {
        val items = JSONArray()
        turns.forEach { items.put(it) }
        writeRoot(JSONObject().put("items", items))
    }

    fun clear() {
        file.delete()
    }

    private fun readRoot(): JSONObject? {
        val bytes = try {
            file.openRead().use { it.readBytes() }
        } catch (_: java.io.FileNotFoundException) {
            return null
        }
        require(bytes.size >= 28) { "Device turn queue is damaged" }
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
