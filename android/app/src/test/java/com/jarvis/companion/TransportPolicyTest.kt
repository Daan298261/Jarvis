package com.jarvis.companion

import org.junit.Assert.*
import org.junit.Test

class TransportPolicyTest {
    @Test fun acceptsHttpsOriginsOnly() {
        assertEquals("https://192.168.1.3:4781", TransportPolicy.origin("https://192.168.1.3:4781/"))
        for (url in listOf("http://jarvis", "https://key@jarvis", "https://jarvis/api", "https://jarvis?token=x", "https://jarvis#secret", "https://jarvis:0", "https://jarvis:65536", "https://jarvis/%2f")) {
            assertThrows(IllegalArgumentException::class.java) { TransportPolicy.origin(url) }
        }
    }
    @Test fun retriesOnlyReadsAndJournaledMessages() {
        assertTrue(TransportPolicy.replayable("GET", "/tasks", null))
        assertTrue(TransportPolicy.replayable("POST", "/messages", "stable-id"))
        assertFalse(TransportPolicy.replayable("POST", "/messages", null))
        for (path in listOf("/calls", "/schedules", "/session", "/attachments", "/tasks/one/approve")) {
            assertFalse(TransportPolicy.replayable("POST", path, "not-a-message"))
        }
    }

    @Test fun pairingFailoverIncludesEnrollAndChallenge() {
        assertTrue(TransportPolicy.pairingFailover("/enroll"))
        assertTrue(TransportPolicy.pairingFailover("/challenge/device-1"))
        assertFalse(TransportPolicy.pairingFailover("/messages"))
    }

    @Test fun ordersPublicAndRelayBeforePrivateLan() {
        val ordered = TransportPolicy.orderedForReachability(
            listOf(
                "https://10.2.0.2:4781",
                "https://relay.example.test:4781",
                "https://203.0.113.4:4781",
            ),
        )
        assertEquals("https://relay.example.test:4781", ordered[0])
        assertEquals("https://203.0.113.4:4781", ordered[1])
        assertEquals("https://10.2.0.2:4781", ordered.last())
    }
}
