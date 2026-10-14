package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LanBeaconTest {
    @Test
    fun round_trips_valid_lan_host() {
        val pin = "a".repeat(64)
        val encoded = LanBeacon.encode(LanHost("https://192.168.1.12:4781", pin, AnzuBranding.DISPLAY_NAME))
        val parsed = LanBeacon.parse(encoded)
        assertNotNull(parsed)
        assertEquals("https://192.168.1.12:4781", parsed!!.endpoint)
        assertEquals(pin, parsed.serverPin)
        assertEquals(AnzuBranding.DISPLAY_NAME, parsed.name)
    }

    @Test
    fun default_discovery_name_is_anzu() {
        val pin = "a".repeat(64)
        assertEquals("ANZU", LanHost("https://192.168.1.12:4781", pin).name)
        val parsed = LanBeacon.parse(
            """{"service":"jarvis-companion","https":"https://192.168.1.12:4781","server_pin":"$pin"}""".toByteArray(),
        )
        assertNotNull(parsed)
        assertEquals("ANZU", parsed!!.name)
    }

    @Test
    fun rejects_loopback_http_and_short_pins() {
        assertNull(LanBeacon.parse("""{"service":"jarvis-companion","https":"https://127.0.0.1:4781","server_pin":"${"b".repeat(64)}"}""".toByteArray()))
        assertNull(LanBeacon.parse("""{"service":"other","https":"https://192.168.1.3:4781","server_pin":"${"b".repeat(64)}"}""".toByteArray()))
        assertNull(LanBeacon.parse("""{"service":"jarvis-companion","https":"http://192.168.1.3:4781","server_pin":"${"b".repeat(64)}"}""".toByteArray()))
        assertNull(LanBeacon.parse("not-json".toByteArray()))
    }

    @Test
    fun parses_endpoint_candidates_and_prefers_home_lan() {
        val pin = "c".repeat(64)
        val raw = """{"service":"jarvis-companion","https":"https://10.2.0.2:4781","endpoints":["https://10.2.0.2:4781","https://192.168.1.212:4781"],"server_pin":"$pin","name":"ANZU"}""".toByteArray()
        val parsed = LanBeacon.parse(raw)
        assertNotNull(parsed)
        assertTrue(parsed!!.endpoints.contains("https://192.168.1.212:4781"))
        assertTrue(parsed.endpoints.contains("https://10.2.0.2:4781"))
        // Without local NIC info the soft rank still prefers 192.168 over VPN 10/8.
        assertEquals("https://192.168.1.212:4781", parsed.endpoint)
    }
}

class LanScannerSelectionTest {
    @Test
    fun pickBestPrefersAttachedLanOverVpnBeacon() {
        val pin = "d".repeat(64)
        val vpn = LanHost("https://10.2.0.2:4781", pin, "ANZU", listOf("https://10.2.0.2:4781"))
        val home = LanHost(
            "https://192.168.1.212:4781",
            pin,
            "ANZU",
            listOf("https://192.168.1.212:4781", "https://10.2.0.2:4781"),
        )
        val locals = listOf("192.168.1.148/24")
        val merged = LanScanner.selectBetter(vpn, home, locals)
        assertEquals("https://192.168.1.212:4781", merged.endpoint)
        assertTrue(merged.endpoints.contains("https://10.2.0.2:4781"))
        val best = LanScanner.pickBest(listOf(vpn, home), locals)
        assertNotNull(best)
        assertEquals("https://192.168.1.212:4781", best!!.endpoint)
    }
}

class PresenceParticlesTest {

    @Test
    fun orb_and_humanoid_are_non_empty_clouds() {
        val orb = PresenceParticles.orb()
        val humanoid = PresenceParticles.humanoid()
        assertTrue(orb.size > 80)
        assertTrue(humanoid.size > PresenceVisual.HUMANOID_MIN_PARTICLES)
        assertTrue(humanoid.any { it.y > 1.0f })
        assertTrue(humanoid.any { it.y < 0f })
        assertEquals(orb.size, PresenceParticles.orb().size)
    }
}
