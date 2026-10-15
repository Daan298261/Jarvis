package com.jarvis.companion

import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Unit-test double: same AES-GCM wire format as production, no Android Keystore. */
internal class JvmAesOutboxQueueCrypto(seed: Int = 0x5A) : OutboxQueueCrypto {
    private val key = SecretKeySpec(ByteArray(32) { seed.toByte() }, "AES")

    override fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key)
        return cipher.iv + cipher.doFinal(plain)
    }

    override fun decrypt(stored: ByteArray): ByteArray {
        require(stored.size >= 28) { "Offline queue payload is damaged" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, stored.copyOfRange(0, 12)))
        return cipher.doFinal(stored.copyOfRange(12, stored.size))
    }
}
