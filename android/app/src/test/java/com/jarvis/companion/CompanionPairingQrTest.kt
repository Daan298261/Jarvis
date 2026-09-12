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

    @Test fun rejects_non_https_or_incomplete_envelopes() {
        assertThrows(IllegalArgumentException::class.java) {
            CompanionPairingQrParser.parse("""{"endpoint":"http://example.test","server_pin":"${"a".repeat(64)}","code":"123456"}""")
        }
        assertThrows(IllegalArgumentException::class.java) {
            CompanionPairingQrParser.parse("""{"endpoint":"https://example.test","server_pin":"short","code":"123"}""")
        }
    }
}
