package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class CompanionPairingQrTest {
    @Test fun parses_valid_desktop_pairing_envelope() {
        val result = CompanionPairingQrParser.parse(
            """{"endpoint":"https://192.168.1.5:4781","server_pin":"${"a".repeat(64)}","code":"123456"}""",
        )
        assertEquals("https://192.168.1.5:4781", result.endpoint)
        assertEquals("123456", result.code)
    }

    @Test fun prefers_reachable_endpoint_from_qr_list() {
        val pin = "a".repeat(64)
        val result = CompanionPairingQrParser.parse(
            """{"endpoint":"https://10.2.0.2:4781","endpoints":["https://10.2.0.2:4781","https://203.0.113.8:4781"],"server_pin":"$pin","code":"471935"}""",
        )
        assertEquals("https://203.0.113.8:4781", result.endpoint)
        assertEquals(listOf("https://203.0.113.8:4781", "https://10.2.0.2:4781"), result.endpoints)
    }

    @Test fun rejects_non_https_or_incomplete_envelopes() {
        assertThrows(IllegalArgumentException::class.java) {
            CompanionPairingQrParser.parse("""{"endpoint":"http://example.test","server_pin":"${"a".repeat(64)}","code":"123456"}""")
        }
        assertThrows(IllegalArgumentException::class.java) {
            CompanionPairingQrParser.parse("""{"endpoint":"https://example.test","server_pin":"short","code":"123"}""")
        }
    }
}
