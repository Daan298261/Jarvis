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
        val encoded = LanBeacon.encode(LanHost("https://192.168.1.12:4781", pin, "Jarvis"))
        val parsed = LanBeacon.parse(encoded)
        assertNotNull(parsed)
        assertEquals("https://192.168.1.12:4781", parsed!!.endpoint)
        assertEquals(pin, parsed.serverPin)
    }

    @Test
    fun rejects_loopback_http_and_short_pins() {
        assertNull(LanBeacon.parse("""{"service":"jarvis-companion","https":"https://127.0.0.1:4781","server_pin":"${"b".repeat(64)}"}""".toByteArray()))
        assertNull(LanBeacon.parse("""{"service":"other","https":"https://192.168.1.3:4781","server_pin":"${"b".repeat(64)}"}""".toByteArray()))
        assertNull(LanBeacon.parse("""{"service":"jarvis-companion","https":"http://192.168.1.3:4781","server_pin":"${"b".repeat(64)}"}""".toByteArray()))
        assertNull(LanBeacon.parse("not-json".toByteArray()))
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
