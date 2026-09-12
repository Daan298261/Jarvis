package com.jarvis.companion

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class CompanionPairingQr(val endpoint: String, val serverPin: String, val code: String)

object CompanionPairingQrParser {
    fun parse(raw: String): CompanionPairingQr {
        val payload = try {
            Json.parseToJsonElement(raw).jsonObject
        } catch (_: Exception) {
            throw IllegalArgumentException("That QR code is not a Jarvis pairing invitation.")
        }
        val endpoint = TransportPolicy.origin(payload["endpoint"]?.jsonPrimitive?.content.orEmpty())
        val pin = payload["server_pin"]?.jsonPrimitive?.content.orEmpty().trim().lowercase()
        require(pin.matches(Regex("[a-f0-9]{64}"))) {
            "The pairing QR code has an invalid server fingerprint."
        }
        val code = when (val validation = CompanionCodeValidator.validate(payload["code"]?.jsonPrimitive?.content.orEmpty())) {
            is CompanionCodeValidation.Valid -> validation.code
            else -> throw IllegalArgumentException("The pairing QR code needs a valid 6-digit code.")
        }
        return CompanionPairingQr(endpoint, pin, code)
    }
}
