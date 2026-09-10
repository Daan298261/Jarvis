package com.jarvis.companion

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONObject

/**
 * RFC-0063 — companion enroll over the mobile gateway.
 *
 * POST /api/mobile/companion/enroll
 * Body: { "code": "012345", "public_key": "...", "name": "Pixel 8" }
 */
class CompanionEnrollClient(
    private val baseUrl: String,
    private val connectTimeoutMs: Int = 15_000,
    private val readTimeoutMs: Int = 15_000,
) {
    fun enroll(
        code: String,
        publicKey: String,
        deviceName: String,
    ): CompanionEnrollResult {
        val validation = CompanionCodeValidator.validate(code)
        if (validation is CompanionCodeValidation.Invalid) {
            return CompanionEnrollResult.InvalidCode(validation.message)
        }
        if (validation is CompanionCodeValidation.Incomplete) {
            return CompanionEnrollResult.InvalidCode("Enter all 6 digits.")
        }
        val normalizedCode = (validation as CompanionCodeValidation.Valid).code

        return try {
            postEnroll(normalizedCode, publicKey.trim(), deviceName.trim())
        } catch (err: IOException) {
            CompanionEnrollResult.NetworkError(err.message ?: "Network error")
        }
    }

    private fun postEnroll(code: String, publicKey: String, deviceName: String): CompanionEnrollResult {
        val endpoint = baseUrl.trimEnd('/') + "/api/mobile/companion/enroll"
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = connectTimeoutMs
            readTimeout = readTimeoutMs
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
        }

        val payload = JSONObject()
            .put("code", code)
            .put("public_key", publicKey)
            .put("name", deviceName.ifBlank { "Android companion" })
            .toString()

        connection.outputStream.use { stream ->
            stream.write(payload.toByteArray(Charsets.UTF_8))
        }

        val status = connection.responseCode
        val body = readBody(connection, status)
        connection.disconnect()

        return when (status) {
            in 200..299 -> CompanionEnrollResult.Success(parseJson(body))
            400, 422 -> CompanionEnrollResult.InvalidCode(extractError(body, "Invalid pairing code."))
            401, 403 -> CompanionEnrollResult.Unauthorized(extractError(body, "Not authorized to enroll."))
            404 -> CompanionEnrollResult.ApiUnavailable("Pairing API is not available yet.")
            410, 408 -> CompanionEnrollResult.Expired(extractError(body, "Pairing code expired. Ask for a new code on the PC."))
            429 -> CompanionEnrollResult.RateLimited(extractError(body, "Too many attempts. Wait and try again."))
            else -> CompanionEnrollResult.ServerError(status, extractError(body, "Enrollment failed ($status)."))
        }
    }

    private fun readBody(connection: HttpURLConnection, status: Int): String {
        val stream = if (status >= 400) connection.errorStream else connection.inputStream
        return stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
    }

    private fun parseJson(body: String): Map<String, String> {
        if (body.isBlank()) return emptyMap()
        val json = JSONObject(body)
        return buildMap {
            json.keys().forEach { key ->
                put(key, json.optString(key, ""))
            }
        }
    }

    private fun extractError(body: String, fallback: String): String {
        if (body.isBlank()) return fallback
        return try {
            val json = JSONObject(body)
            json.optString("detail", json.optString("message", fallback)).ifBlank { fallback }
        } catch (_: Exception) {
            body.take(200).ifBlank { fallback }
        }
    }
}

sealed class CompanionEnrollResult {
    data class Success(val payload: Map<String, String>) : CompanionEnrollResult()
    data class InvalidCode(val message: String) : CompanionEnrollResult()
    data class Expired(val message: String) : CompanionEnrollResult()
    data class RateLimited(val message: String) : CompanionEnrollResult()
    data class Unauthorized(val message: String) : CompanionEnrollResult()
    data class ApiUnavailable(val message: String) : CompanionEnrollResult()
    data class NetworkError(val message: String) : CompanionEnrollResult()
    data class ServerError(val status: Int, val message: String) : CompanionEnrollResult()
}
