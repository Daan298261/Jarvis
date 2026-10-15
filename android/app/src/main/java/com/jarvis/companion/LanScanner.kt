package com.jarvis.companion

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface

object LanScanner {
    suspend fun scan(timeoutMs: Long = 2800): LanHost? = withContext(Dispatchers.IO) {
        DatagramSocket().use { socket ->
            socket.broadcast = true
            socket.soTimeout = 350
            val probe = LanBeacon.probeBytes()
            val destinations = broadcastTargets()
            val deadline = System.currentTimeMillis() + timeoutMs
            val locals = TransportPolicy.localIpv4Addresses()
            val seen = linkedMapOf<String, LanHost>()
            while (System.currentTimeMillis() < deadline) {
                destinations.forEach { address ->
                    runCatching {
                        socket.send(DatagramPacket(probe, probe.size, address, LanBeacon.PORT))
                    }
                }
                val buffer = ByteArray(1500)
                val packet = DatagramPacket(buffer, buffer.size)
                val received = runCatching {
                    socket.receive(packet)
                    true
                }.getOrDefault(false)
                if (received) {
                    val host = LanBeacon.parse(packet.data.copyOf(packet.length))
                    if (host != null) {
                        val key = host.serverPin
                        val previous = seen[key]
                        seen[key] = selectBetter(previous, host, locals)
                        // Fast path: already have an origin on the phone's Wi-Fi.
                        if (TransportPolicy.onAttachedLan(seen[key]!!.endpoint, locals)) {
                            val remaining = deadline - System.currentTimeMillis()
                            if (remaining < 400) return@withContext seen[key]
                        }
                    }
                }
            }
            pickBest(seen.values.toList(), locals)
        }
    }

    internal fun selectBetter(current: LanHost?, candidate: LanHost, localIpv4: Iterable<String>): LanHost {
        if (current == null) return candidate
        val merged = TransportPolicy.dialOrder(
            null,
            current.endpoints + current.endpoint + candidate.endpoints + candidate.endpoint,
            localIpv4,
        )
        val primary = merged.firstOrNull() ?: candidate.endpoint
        val name = when {
            TransportPolicy.onAttachedLan(candidate.endpoint, localIpv4) -> candidate.name
            TransportPolicy.onAttachedLan(current.endpoint, localIpv4) -> current.name
            else -> candidate.name.ifBlank { current.name }
        }
        return LanHost(primary, candidate.serverPin.ifBlank { current.serverPin }, name, merged)
    }

    internal fun pickBest(hosts: List<LanHost>, localIpv4: Iterable<String>): LanHost? {
        if (hosts.isEmpty()) return null
        return hosts
            .map { host -> selectBetter(null, host, localIpv4) }
            .minWith(
                compareBy(
                    { if (TransportPolicy.onAttachedLan(it.endpoint, localIpv4)) 0 else 1 },
                    { TransportPolicy.lanCandidateRank(it.endpoint) },
                    { it.endpoint },
                ),
            )
    }

    internal fun broadcastTargets(): List<InetAddress> {
        val found = mutableListOf(InetAddress.getByName("255.255.255.255"))
        runCatching {
            NetworkInterface.getNetworkInterfaces()?.toList().orEmpty().forEach { nic ->
                if (!nic.isUp || nic.isLoopback) return@forEach
                nic.interfaceAddresses.forEach { address ->
                    address.broadcast?.let(found::add)
                }
            }
        }
        return found.distinct()
    }
}
