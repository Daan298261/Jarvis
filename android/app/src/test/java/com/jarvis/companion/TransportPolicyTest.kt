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
}
