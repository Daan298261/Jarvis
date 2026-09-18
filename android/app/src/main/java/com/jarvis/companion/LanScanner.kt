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
                    if (host != null) return@withContext host
                }
            }
        }
        null
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
