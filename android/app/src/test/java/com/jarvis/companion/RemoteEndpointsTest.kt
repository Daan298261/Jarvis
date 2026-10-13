package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64

class RemoteEndpointsTest {
    @Test
    fun recognisesTailscaleHosts() {
        assertTrue(RemoteEndpoints.isTailscaleHost("vrpc.tail1234.ts.net"))
        assertTrue(RemoteEndpoints.isTailscaleHost("100.101.1.2"))
        assertFalse(RemoteEndpoints.isTailscaleHost("100.200.1.2"))
    }

    @Test
    fun tailscaleDialsBeforeOtherHostnames() {
        val ordered = TransportPolicy.orderedForReachability(
            listOf("https://desk.example.com:4781", "https://vrpc.tail1.ts.net:4781"),
        )
        assertEquals("https://vrpc.tail1.ts.net:4781", ordered.first())
    }

    @Test
    fun serverProofMustMatchPinnedKey() {
        val gen = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }
        val server = gen.generateKeyPair()
        val der = server.public.encoded
        val pin = MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }
        val sig = Signature.getInstance("SHA256withECDSA").run {
            initSign(server.private); update("anzu-server-v1\nn0nce".toByteArray()); sign()
        }
        val key = Base64.getEncoder().encodeToString(der)
        val signature = Base64.getEncoder().encodeToString(sig)
        assertTrue(RemoteEndpoints.verifyServerProof(pin, "n0nce", key, signature))
        assertFalse(RemoteEndpoints.verifyServerProof(pin, "other", key, signature))
        val impostor = Base64.getEncoder().encodeToString(gen.generateKeyPair().public.encoded)
        assertFalse(RemoteEndpoints.verifyServerProof(pin, "n0nce", impostor, signature))
        // Missing proof (old or impostor server) must fail, so the session is refused.
        assertFalse(RemoteEndpoints.verifyServerProof(pin, "n0nce", "", ""))
        assertFalse(RemoteEndpoints.verifyServerProof(pin, "n0nce", key, ""))
    }

    @Test
    fun tailscaleHintExplainsMissingOrOffApp() {
        val eps = listOf("https://vrpc.tail1.ts.net:4781")
        assertNotNull(RemoteEndpoints.tailscaleHint(eps, appInstalled = false, vpnActive = false, onLan = false))
        assertTrue(RemoteEndpoints.tailscaleHint(eps, true, false, false)!!.contains("switch it on"))
        assertNull(RemoteEndpoints.tailscaleHint(eps, true, true, false))
        assertNull(RemoteEndpoints.tailscaleHint(eps, false, false, onLan = true))
        assertNull(RemoteEndpoints.tailscaleHint(listOf("https://203.0.113.1:4781"), false, false, false))
    }
}
