package com.jarvis.companion

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class SessionRecoveryTest {
    @Test fun restartTokenRejectionRetriesOnce() = runBlocking {
        var calls = 0
        val result = recoverExpiredRead("GET") {
            if (++calls == 1) throw ApiException(401, "expired")
            "reconnected"
        }
        assertEquals("reconnected", result)
        assertEquals(2, calls)
    }
    @Test fun mutationAndRevocationNeverReplay() = runBlocking {
        for ((method, status) in listOf("POST" to 401, "GET" to 403, "GET" to 401)) {
            var calls = 0
            try { recoverExpiredRead(method) { calls++; throw ApiException(status, "rejected") } }
            catch (_: ApiException) { }
            assertEquals(if (method == "GET" && status == 401) 2 else 1, calls)
        }
    }
}
