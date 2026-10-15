package com.jarvis.companion

/** Only reads may be replayed after a rejected token; writes retain their existing outbox/idempotency rules. */
internal suspend fun <T> recoverExpiredRead(method: String, request: suspend () -> T): T =
    try { request() } catch (error: ApiException) {
        if (error.status != 401 || method != "GET") throw error
        request()
    }
