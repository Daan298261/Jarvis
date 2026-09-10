package com.jarvis.companion

import java.net.URI

object TransportPolicy {
    fun origin(value: String): String {
        val parsed = URI(value.trim())
        require(parsed.scheme == "https" && parsed.host != null && parsed.rawUserInfo == null &&
            parsed.rawQuery == null && parsed.rawFragment == null && parsed.rawPath.orEmpty().trim('/').isEmpty() &&
            (parsed.port == -1 || parsed.port in 1..65535)) { "Enter an HTTPS server origin, without a path or credentials" }
        return value.trim().trimEnd('/')
    }
    fun replayable(method: String, path: String, requestId: String?): Boolean =
        method == "GET" || (method == "POST" && path == "/messages" && !requestId.isNullOrBlank())
}
