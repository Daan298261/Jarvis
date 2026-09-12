package com.jarvis.companion

import org.json.JSONObject

data class CompanionPairingQr(val endpoint: String, val serverPin: String, val code: String)

object CompanionPairingQrParser {
    fun parse(raw: String): CompanionPairingQr {
        val payload = try {
            JSONObject(raw)
        } catch (_: Exception) {
            throw IllegalArgumentException("That QR code is not a Jarvis pairing invitation.")
        }
        val endpoint = TransportPolicy.origin(payload.optString("endpoint"))
        val pin = payload.optString("server_pin").trim().lowercase()
        require(pin.matches(Regex("[a-f0-9]{64}"))) {
            "The pairing QR code has an invalid server fingerprint."
        }
        val code = when (val validation = CompanionCodeValidator.validate(payload.optString("code"))) {
            is CompanionCodeValidation.Valid -> validation.code
            else -> throw IllegalArgumentException("The pairing QR code needs a valid 6-digit code.")
        }
        return CompanionPairingQr(endpoint, pin, code)
    }
}
