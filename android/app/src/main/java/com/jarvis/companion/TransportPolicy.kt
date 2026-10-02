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

    fun mayRaceOrigins(
        method: String,
        path: String,
        addresses: List<String> = emptyList(),
        localIpv4: Iterable<String> = emptyList(),
    ): Boolean {
        if (method != "GET" || pairingFailover(path)) return false
        val first = addresses.firstOrNull() ?: return true
        return !onAttachedLan(first, localIpv4)
    }

    fun connectTimeoutMs(originCount: Int): Long = if (originCount > 1) 1_500L else 4_000L

    fun orderedForReachability(addresses: Iterable<String>): List<String> {
        val distinct = addresses.map { origin(it) }.distinct()
        return distinct.sortedWith(compareBy({ reachabilityRank(it) }, { it }))
    }

    fun localIpv4Addresses(): List<String> = runCatching {
        NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
            .filter { nic ->
                runCatching { nicIsLanDialSource(nic.isUp, nic.isLoopback, nic.isVirtual, nic.isPointToPoint) }
                    .getOrDefault(false)
            }
            .flatMap { nic -> nic.interfaceAddresses }
            .mapNotNull { ia ->
                val addr = ia.address as? Inet4Address ?: return@mapNotNull null
                val host = addr.hostAddress?.substringBefore('%').orEmpty()
                val octets = parseV4(host) ?: return@mapNotNull null
                if (!isRfc1918(octets)) return@mapNotNull null
                val prefix = ia.networkPrefixLength.toInt().coerceIn(8, 30)
                "$host/$prefix"
            }
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
        val home = usable.filter { onAttachedLan(it, locals) }
        if (home.isNotEmpty()) {
            val head = home.first()
            return (listOf(head) + usable.filter { it != head } + deferred).distinct()
        }
        val sticky = recent?.let { runCatching { origin(it) }.getOrNull() }
        val useSticky = sticky != null && sticky !in skip &&
            (onAttachedLan(sticky, locals) || reachabilityRank(sticky) < 2)
        val head = if (useSticky) sticky else null
        return (listOfNotNull(head) + usable.filter { it != head } + deferred).distinct()
    }

    internal fun nicIsLanDialSource(up: Boolean, loopback: Boolean, virtual: Boolean, pointToPoint: Boolean): Boolean =
        up && !loopback && !virtual && !pointToPoint

    internal fun isLanHostname(host: String): Boolean {
        val value = host.trim().lowercase().trimEnd('.')
        if (value.isEmpty()) return false
        if (value in setOf("localhost", "router", "gateway")) return true
        return value.endsWith(".local") || value.endsWith(".lan") || value.endsWith(".home.arpa")
    }

    internal fun onAttachedLan(endpoint: String, localIpv4: Iterable<String>): Boolean {
        val host = runCatching { URI(endpoint).host?.trim().orEmpty() }.getOrDefault("")
        val locals = localIpv4.mapNotNull { parseLocal(it) }
        if (locals.isEmpty()) return false
        if (isLanHostname(host)) return true
        val target = parseV4(host) ?: return false
        if (!isRfc1918(target)) return false
        return locals.any { (ip, prefix) -> sameNetwork(ip, target, prefix) }
    }

    internal fun parseLocal(raw: String): Pair<IntArray, Int>? {
        val text = raw.trim()
        val slash = text.indexOf('/')
        val ipPart = if (slash >= 0) text.substring(0, slash) else text
        val prefix = if (slash >= 0) {
            text.substring(slash + 1).toIntOrNull()?.coerceIn(8, 30) ?: return null
        } else {
            24
        }
        val ip = parseV4(ipPart) ?: return null
        if (!isRfc1918(ip)) return null
        return ip to prefix
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

    internal fun sameNetwork(a: IntArray, b: IntArray, prefix: Int): Boolean {
        if (a.size != 4 || b.size != 4) return false
        var remaining = prefix.coerceIn(8, 32)
        for (i in 0..3) {
            if (remaining <= 0) return true
            val take = minOf(8, remaining)
            val shift = 8 - take
            val mask = (0xFF shl shift) and 0xFF
            if ((a[i] and mask) != (b[i] and mask)) return false
            remaining -= take
        }
        return true
    }

    internal fun sameSlash24(a: IntArray, b: IntArray): Boolean = sameNetwork(a, b, 24)

    internal fun reachabilityRank(value: String): Int {
        val host = runCatching { URI(value).host?.trim()?.lowercase().orEmpty() }.getOrDefault("")
        if (host.isEmpty()) return 2
        if (isLanHostname(host)) return 2
        val numeric = host.matches(Regex("""^\d{1,3}(\.\d{1,3}){3}$""")) || host.contains(':')
        if (!numeric) return 0
        val ip = runCatching { InetAddress.getByName(host) }.getOrNull() ?: return 1
        return if (ip.isLoopbackAddress || ip.isLinkLocalAddress || ip.isSiteLocalAddress) 2 else 1
    }
}
