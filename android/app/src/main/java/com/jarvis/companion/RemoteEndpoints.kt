package com.jarvis.companion

import java.net.URI
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64

/**
 * RFC-0215 off-LAN endpoints: Tailscale is the only remote path. Every origin is
 * still pinned to the desktop gateway key, and each session also requires a
 * desktop signature over a fresh phone nonce made with that same key.
 */
object RemoteEndpoints {
    const val TAILSCALE_PACKAGE = "com.tailscale.ipn"

    fun host(origin: String): String =
        runCatching { URI(origin).host?.trim('[', ']')?.lowercase()?.trimEnd('.').orEmpty() }.getOrDefault("")

    fun isTailscaleHost(host: String): Boolean {
        val value = host.lowercase().trimEnd('.')
        if (value.endsWith(".ts.net")) return true
        if (value.startsWith("fd7a:115c:a1e0:")) return true
        val octets = TransportPolicy.parseV4(value) ?: return false
        return octets[0] == 100 && octets[1] in 64..127
    }

    /** Tie-break within TransportPolicy's rank: Tailscale before other hostnames. */
    fun tier(origin: String): Int = if (isTailscaleHost(host(origin))) 0 else 1

    /** Verify the desktop signed our nonce with the key whose SPKI hash is the QR pin. */
    fun verifyServerProof(pin: String, nonce: String, serverKeyB64: String, signatureB64: String): Boolean = runCatching {
        val der = Base64.getDecoder().decode(serverKeyB64)
        val digest = MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }
        if (digest != pin.lowercase()) return false
        val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(der))
        Signature.getInstance("SHA256withECDSA").run {
            initVerify(key)
            update("anzu-server-v1\n$nonce".toByteArray())
            verify(Base64.getDecoder().decode(signatureB64))
        }
    }.getOrDefault(false)

    /** Explain why off-LAN endpoints failed when Tailscale is the path but not up on the phone. */
    fun tailscaleHint(endpoints: List<String>, appInstalled: Boolean, vpnActive: Boolean, onLan: Boolean): String? {
        if (onLan || endpoints.none { isTailscaleHost(host(it)) }) return null
        if (!appInstalled) return "ANZU is reachable over Tailscale. Install the Tailscale app, sign in with the same account as your PC, and turn it on."
        if (!vpnActive) return "Tailscale is not connected on this phone. Open the Tailscale app and switch it on, then retry."
        return null
    }
}
