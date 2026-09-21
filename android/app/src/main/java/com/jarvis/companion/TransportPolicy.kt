package com.jarvis.companion

import java.net.InetAddress
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

    fun pairingFailover(path: String): Boolean =
        path == "/enroll" || path == "/lan-enroll" || path == "/session" || path.startsWith("/challenge/")

    fun orderedForReachability(addresses: Iterable<String>): List<String> {
        val distinct = addresses.map { origin(it) }.distinct()
        return distinct.sortedWith(compareBy({ reachabilityRank(it) }, { it }))
    }

    internal fun reachabilityRank(value: String): Int {
        val host = runCatching { URI(value).host?.trim()?.lowercase().orEmpty() }.getOrDefault("")
        if (host.isEmpty()) return 2
        val numeric = host.matches(Regex("""^\d{1,3}(\.\d{1,3}){3}$""")) || host.contains(':')
        if (!numeric) return 0
        val ip = runCatching { InetAddress.getByName(host) }.getOrNull() ?: return 1
        return if (ip.isLoopbackAddress || ip.isLinkLocalAddress || ip.isSiteLocalAddress) 2 else 1
    }
}
