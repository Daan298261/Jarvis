package com.jarvis.companion

import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
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

    fun mayRaceOrigins(method: String, path: String): Boolean =
        method == "GET" && !pairingFailover(path)

    fun connectTimeoutMs(originCount: Int): Long = if (originCount > 1) 1_500L else 4_000L

    fun orderedForReachability(addresses: Iterable<String>): List<String> {
        val distinct = addresses.map { origin(it) }.distinct()
        return distinct.sortedWith(compareBy({ reachabilityRank(it) }, { it }))
    }

    fun localIpv4Addresses(): List<String> = runCatching {
        NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
            .filter { runCatching { it.isUp && !it.isLoopback }.getOrDefault(false) }
            .flatMap { nic -> nic.inetAddresses.toList() }
            .mapNotNull { addr -> (addr as? Inet4Address)?.hostAddress }
            .map { it.substringBefore('%') }
            .filter { it.isNotBlank() && it != "127.0.0.1" }
            .distinct()
    }.getOrDefault(emptyList())

    fun dialOrder(
        recent: String?,
        candidates: Iterable<String>,
        localIpv4: Iterable<String> = emptyList(),
        skipped: Iterable<String> = emptyList(),
    ): List<String> {
        val rest = orderedForReachability(candidates + listOfNotNull(recent))
        val locals = localIpv4.map { it.trim() }.filter { it.isNotEmpty() }
        val skip = skipped.mapNotNull { runCatching { origin(it) }.getOrNull() }.toSet()
        val usable = rest.filter { it !in skip }
        val deferred = rest.filter { it in skip }
        if (locals.isNotEmpty()) {
            val home = usable.filter { onAttachedLan(it, locals) }
            if (home.isNotEmpty()) {
                val head = home.first()
                return (listOf(head) + usable.filter { it != head } + deferred).distinct()
            }
            val sticky = recent?.let { runCatching { origin(it) }.getOrNull() }
            val useSticky = sticky != null && sticky !in skip && reachabilityRank(sticky) < 2
            val head = if (useSticky) sticky else null
            return (listOfNotNull(head) + usable.filter { it != head } + deferred).distinct()
        }
        val head = recent?.let { runCatching { origin(it) }.getOrNull() }?.takeIf { it !in skip }
        return (listOfNotNull(head) + usable.filter { it != head } + deferred).distinct()
    }

    internal fun onAttachedLan(endpoint: String, localIpv4: Iterable<String>): Boolean {
        val host = runCatching { URI(endpoint).host?.trim().orEmpty() }.getOrDefault("")
        val target = parseV4(host) ?: return false
        if (!isRfc1918(target)) return false
        return localIpv4.any { local ->
            val ip = parseV4(local) ?: return@any false
            sameSlash24(ip, target)
        }
    }

    internal fun parseV4(host: String): IntArray? {
        val parts = host.trim().split('.')
        if (parts.size != 4) return null
        val nums = IntArray(4)
        for (i in 0..3) {
            val value = parts[i].toIntOrNull() ?: return null
            if (value !in 0..255) return null
            nums[i] = value
        }
        return nums
    }

    internal fun isRfc1918(octets: IntArray): Boolean {
        val a = octets[0]
        val b = octets[1]
        return a == 10 || (a == 172 && b in 16..31) || (a == 192 && b == 168)
    }

    internal fun sameSlash24(a: IntArray, b: IntArray): Boolean =
        a.size == 4 && b.size == 4 && a[0] == b[0] && a[1] == b[1] && a[2] == b[2]

    internal fun reachabilityRank(value: String): Int {
        val host = runCatching { URI(value).host?.trim()?.lowercase().orEmpty() }.getOrDefault("")
        if (host.isEmpty()) return 2
        val numeric = host.matches(Regex("""^\d{1,3}(\.\d{1,3}){3}$""")) || host.contains(':')
        if (!numeric) return 0
        val ip = runCatching { InetAddress.getByName(host) }.getOrNull() ?: return 1
        return if (ip.isLoopbackAddress || ip.isLinkLocalAddress || ip.isSiteLocalAddress) 2 else 1
    }
}
