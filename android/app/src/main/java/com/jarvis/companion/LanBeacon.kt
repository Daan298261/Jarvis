package com.jarvis.companion

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.URI
import java.nio.charset.StandardCharsets

data class LanHost(
    val endpoint: String,
    val serverPin: String,
    val name: String = "Jarvis",
)

object LanBeacon {
    const val PORT = 4782
    const val MAGIC = "JARVIS1"
    const val SERVICE = "jarvis-companion"

    fun probeBytes(): ByteArray = "$MAGIC\n{\"probe\":true}".toByteArray(StandardCharsets.UTF_8)

    fun parse(raw: ByteArray): LanHost? {
        val text = raw.toString(StandardCharsets.UTF_8).trim()
        val jsonText = when {
            text.startsWith("$MAGIC\n") -> text.substring(MAGIC.length + 1)
            text.startsWith("{") -> text
            else -> return null
        }
        return runCatching {
            val payload = Json.parseToJsonElement(jsonText).jsonObject
            if (payload["probe"]?.jsonPrimitive?.booleanOrNull == true) return@runCatching null
            if (payload["service"]?.jsonPrimitive?.content != SERVICE) return@runCatching null
            val pin = payload["server_pin"]?.jsonPrimitive?.content.orEmpty().trim().lowercase()
            if (!pin.matches(Regex("[a-f0-9]{64}"))) return@runCatching null
            val endpoint = TransportPolicy.origin(payload["https"]?.jsonPrimitive?.content.orEmpty())
            val host = URI(endpoint).host ?: return@runCatching null
            if (host == "127.0.0.1" || host.equals("localhost", ignoreCase = true)) return@runCatching null
            val name = payload["name"]?.jsonPrimitive?.content.orEmpty().ifBlank { "Jarvis" }.take(80)
            LanHost(endpoint, pin, name)
        }.getOrNull()
    }

    fun encode(host: LanHost): ByteArray {
        val escapedName = host.name.replace("\\", "\\\\").replace("\"", "\\\"")
        val body = """{"service":"$SERVICE","version":1,"https":"${host.endpoint}","server_pin":"${host.serverPin}","name":"$escapedName","lan_pair":true}"""
        return "$MAGIC\n$body".toByteArray(StandardCharsets.UTF_8)
    }
}
