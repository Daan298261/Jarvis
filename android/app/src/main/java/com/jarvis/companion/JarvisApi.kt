package com.jarvis.companion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.Signature
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

class ApiException(val status: Int, message: String) : Exception(message)

class JarvisApi(context: Context) {
    private val prefs = context.getSharedPreferences("connection", Context.MODE_PRIVATE)
    private val bootstrap = runCatching { JSONObject(context.assets.open("bootstrap.json").bufferedReader().readText()) }.getOrDefault(JSONObject())
    var endpoint: String = prefs.getString("endpoint", bootstrap.optString("endpoint")) ?: ""
        private set
    var pin: String = prefs.getString("pin", bootstrap.optString("server_pin")) ?: ""
        private set
    var deviceId: String = prefs.getString("device", "") ?: ""
        private set
    val invitation: String get() = bootstrap.optString("invitation")
    val firebase: JSONObject? get() = bootstrap.optJSONObject("firebase")
    private var endpoints = runCatching {
        val supplied = JSONArray(prefs.getString("endpoints", null) ?: bootstrap.optJSONArray("endpoints")?.toString() ?: "[]")
        (0 until supplied.length()).map { TransportPolicy.origin(supplied.getString(it)) }.distinct().take(8)
    }.getOrDefault(emptyList())
    @Volatile private var preferred = ""
    @Volatile private var preferredAt = 0L
    private val failedLock = Any()
    private var failedOrigins: List<Pair<String, Long>> = emptyList()
    @Volatile private var cachedClient: Pair<String, OkHttpClient>? = null
    private var token = ""
    private var expiresAt = 0L
    private val sessionLock = Mutex()
    private val keys = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private val keyAlias = "jarvis-device-v1"

    init {
        if (!keys.containsAlias(keyAlias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder(keyAlias, KeyProperties.PURPOSE_SIGN)
                    .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                    .setDigests(KeyProperties.DIGEST_SHA256).build())
            }.generateKeyPair()
        }
    }

    fun configure(url: String, publicPin: String, candidates: List<String> = emptyList()) {
        require(publicPin.matches(Regex("[a-fA-F0-9]{64}"))) { "Server fingerprint must contain 64 hexadecimal characters" }
        val ordered = TransportPolicy.orderedForReachability(candidates + url).take(8)
        val address = ordered.firstOrNull() ?: TransportPolicy.origin(url)
        val changed = pin != publicPin.lowercase()
        endpoint = address
        pin = publicPin.lowercase()
        if (changed) { deviceId = ""; token = ""; expiresAt = 0; endpoints = emptyList(); cachedClient = null }
        preferred = ""; preferredAt = 0
        synchronized(failedLock) { failedOrigins = emptyList() }
        endpoints = ordered.ifEmpty { listOf(endpoint) }
        prefs.edit().putString("endpoint", endpoint).putString("pin", pin).putString("device", deviceId).putString("endpoints", JSONArray(endpoints).toString()).apply()
    }

    suspend fun refreshEndpoints() {
        val settings = json("/connection")
        if (settings.optString("server_pin") != pin) return
        val values = settings.optJSONArray("endpoints") ?: return
        val incoming = (0 until values.length()).map { values.getString(it) }
        val addresses = TransportPolicy.mergeConnectionEndpoints(endpoints, incoming)
        if (addresses.isNotEmpty()) {
            persistEndpoints(addresses)
        }
    }

    fun absorbMatchingLanOrigin(discovered: String, discoveredPin: String): Boolean {
        val merged = TransportPolicy.absorbMatchingLanOrigin(endpoints, pin, discovered, discoveredPin) ?: return false
        if (merged.isEmpty()) return false
        persistEndpoints(merged)
        return true
    }

    private fun persistEndpoints(addresses: List<String>) {
        endpoints = addresses
        endpoint = addresses.first()
        prefs.edit().putString("endpoint", endpoint).putString("endpoints", JSONArray(addresses).toString()).apply()
    }

    private fun publicKey() = Base64.encodeToString(keys.getCertificate(keyAlias).publicKey.encoded, Base64.NO_WRAP)
    fun fingerprint() = sha256(keys.getCertificate(keyAlias).publicKey.encoded)

    suspend fun pair(credential: String): JSONObject {
        val value = credential.trim()
        val body = JSONObject().put("public_key", publicKey()).put("name", android.os.Build.MODEL)
        when (val validation = CompanionCodeValidator.validate(value)) {
            is CompanionCodeValidation.Valid -> body.put("code", validation.code)
            else -> {
                require(value.length >= 20) { "Enter the 6-digit code shown on your Jarvis desktop" }
                body.put("invitation", value)
            }
        }
        val result = raw("/enroll", "POST", body.toString().toByteArray(), false)
        val device = JSONObject(result.toString(Charsets.UTF_8))
        deviceId = device.getString("id")
        prefs.edit().putString("device", deviceId).apply()
        return device
    }

    suspend fun lanEnroll(): JSONObject {
        val body = JSONObject().put("public_key", publicKey()).put("name", android.os.Build.MODEL)
        val result = raw("/lan-enroll", "POST", body.toString().toByteArray(), false)
        val device = JSONObject(result.toString(Charsets.UTF_8))
        deviceId = device.getString("id")
        prefs.edit().putString("device", deviceId).apply()
        return device
    }

    suspend fun session() = sessionLock.withLock {
        if (token.isNotEmpty() && System.currentTimeMillis() < expiresAt) return@withLock
        check(deviceId.isNotEmpty()) { "Pair this phone first" }
        val challenge = JSONObject(raw("/challenge/$deviceId", authenticated = false).toString(Charsets.UTF_8))
        val proof = Signature.getInstance("SHA256withECDSA").run {
            initSign(keys.getKey(keyAlias, null) as java.security.PrivateKey)
            update("jarvis-mobile-v1\n$deviceId\n${challenge.getString(\"challenge\")}".toByteArray())
            Base64.encodeToString(sign(), Base64.NO_WRAP)
        }
        val result = JSONObject(raw("/session", "POST", JSONObject().put("device_id", deviceId).put("signature", proof).toString().toByteArray(), false).toString(Charsets.UTF_8))
        token = result.getString("access_token")
        expiresAt = System.currentTimeMillis() + (result.getLong("expires_in") - 30) * 1000
    }

    suspend fun ensureSession() = session()
    fun accessToken(): String = token
    fun preferredOrigin(): String = candidateOrigins().firstOrNull() ?: TransportPolicy.origin(endpoint)

    fun candidateOrigins(): List<String> = TransportPolicy.dialOrder(
        preferred.takeIf { it.isNotBlank() },
        endpoints + endpoint,
        TransportPolicy.localIpv4Addresses(),
        recentFailures(),
    )

    fun noteReachable(origin: String) {
        val address = TransportPolicy.origin(origin)
        preferred = address
        preferredAt = System.currentTimeMillis()
        synchronized(failedLock) {
            failedOrigins = failedOrigins.filter { it.first != address }
        }
    }

    fun noteUnreachable(origin: String) {
        noteFailed(origin)
    }

    private fun noteFailed(origin: String) {
        val address = runCatching { TransportPolicy.origin(origin) }.getOrDefault(origin)
        val now = System.currentTimeMillis()
        synchronized(failedLock) {
            failedOrigins = (failedOrigins.filter { now - it.second < 30_000 && it.first != address } + (address to now)).takeLast(8)
        }
    }

    private fun recentFailures(): List<String> {
        val now = System.currentTimeMillis()
        synchronized(failedLock) {
            failedOrigins = failedOrigins.filter { now - it.second < 30_000 }
            return failedOrigins.map { it.first }
        }
    }
    fun pinnedClient(): OkHttpClient {
        require(endpoint.startsWith("https://") && pin.length == 64) { "Set the Jarvis endpoint and server fingerprint" }
        val expectedPin = pin
        return cachedClient?.takeIf { it.first == expectedPin }?.second ?: run {
            val trust = object : X509TrustManager {
                override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
                override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) { throw java.security.cert.CertificateException("Client trust is not supported") }
                override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                    if (chain.isEmpty()) throw java.security.cert.CertificateException("Missing certificate")
                    chain[0].checkValidity()
                    if (sha256(chain[0].publicKey.encoded) != expectedPin) throw java.security.cert.CertificateException("Jarvis server fingerprint changed; verify it on the desktop")
                }
            }
            val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
            OkHttpClient.Builder().sslSocketFactory(tls.socketFactory, trust).retryOnConnectionFailure(false)
                .followRedirects(false).followSslRedirects(false).connectTimeout(4, TimeUnit.SECONDS).readTimeout(90, TimeUnit.SECONDS).build()
                .also { cachedClient = expectedPin to it }
        }
    }

    suspend fun json(path: String, method: String = "GET", body: JSONObject? = null): JSONObject =
        JSONObject(raw(path, method, body?.toString()?.toByteArray()).toString(Charsets.UTF_8))
    suspend fun array(path: String): JSONArray = JSONArray(raw(path).toString(Charsets.UTF_8))

    suspend fun raw(
        path: String,
        method: String = "GET",
        body: ByteArray? = null,
        authenticated: Boolean = true,
        contentType: String = "application/json",
        filename: String? = null,
        extraHeaders: Map<String, String> = emptyMap(),
    ): ByteArray = withContext(Dispatchers.IO) {
        if (authenticated) session()
        require(endpoint.startsWith("https://") && pin.length == 64) { "Set the Jarvis endpoint and server fingerprint" }
        val recent = preferred.takeIf { System.currentTimeMillis() - preferredAt < 60000 }
        val locals = TransportPolicy.localIpv4Addresses()
        val addresses = TransportPolicy.dialOrder(
            recent,
            endpoints + endpoint,
            locals,
            recentFailures(),
        )
        val client = pinnedClient().newBuilder()
            .connectTimeout(TransportPolicy.connectTimeoutMs(addresses.size), TimeUnit.MILLISECONDS)
            .build()
        try {
            if (TransportPolicy.mayRaceOrigins(method, path, addresses, locals) && addresses.size > 1) {
                return@withContext raceOrigins(client, addresses, path, method, body, authenticated, contentType, filename, extraHeaders)
            }
            sequentialOrigins(client, addresses, path, method, body, authenticated, contentType, filename, extraHeaders)
        } catch (error: java.io.IOException) {
            if (!recoverPairedLanFromBeacon()) throw error
            val retryLocals = TransportPolicy.localIpv4Addresses()
            val retryAddresses = TransportPolicy.dialOrder(
                preferred.takeIf { System.currentTimeMillis() - preferredAt < 60_000 },
                endpoints + endpoint,
                retryLocals,
                recentFailures(),
            )
            sequentialOrigins(client, retryAddresses, path, method, body, authenticated, contentType, filename, extraHeaders)
        }
    }

    suspend fun recoverPairedLanFromBeacon(): Boolean {
        if (deviceId.isEmpty() || pin.length != 64) return false
        if (TransportPolicy.localIpv4Addresses().isEmpty()) return false
        val host = runCatching { LanScanner.scan(timeoutMs = 1600) }.getOrNull() ?: return false
        return absorbMatchingLanOrigin(host.endpoint, host.serverPin)
    }

    private fun sequentialOrigins(
        client: OkHttpClient,
        addresses: List<String>,
        path: String,
        method: String,
        body: ByteArray?,
        authenticated: Boolean,
        contentType: String,
        filename: String?,
        extraHeaders: Map<String, String>,
    ): ByteArray {
        var failure: java.io.IOException? = null
        for (address in addresses) {
            try {
                return callOrigin(client, address, path, method, body, authenticated, contentType, filename, extraHeaders)
            } catch (error: java.io.IOException) {
                noteFailed(address)
                failure = error
            }
        }
        throw failure ?: java.io.IOException("No reachable Jarvis endpoint")
    }

    private suspend fun raceOrigins(
        client: OkHttpClient,
        addresses: List<String>,
        path: String,
        method: String,
        body: ByteArray?,
        authenticated: Boolean,
        contentType: String,
        filename: String?,
        extraHeaders: Map<String, String>,
    ): ByteArray = coroutineScope {
        val outcomes = Channel<Result<ByteArray>>(Channel.UNLIMITED)
        val calls = mutableListOf<okhttp3.Call>()
        val jobs = addresses.mapIndexed { index, address ->
            launch {
                if (index > 0) delay(200L * index)
                val call = client.newCall(
                    originRequest(address, path, method, body, authenticated, contentType, filename, extraHeaders),
                )
                synchronized(calls) { calls.add(call) }
                try {
                    outcomes.send(Result.success(readOrigin(call, address)))
                } catch (error: CancellationException) {
                    call.cancel()
                    throw error
                } catch (error: java.io.IOException) {
                    noteFailed(address)
                    outcomes.send(Result.failure(error))
                } catch (error: Throwable) {
                    outcomes.send(Result.failure(error))
                }
            }
        }
        var remaining = addresses.size
        var failure: java.io.IOException? = null
        while (remaining > 0) {
            remaining -= 1
            val next = outcomes.receive()
            val error = next.exceptionOrNull()
            if (error is ApiException) {
                jobs.forEach { it.cancel() }
                synchronized(calls) { calls.forEach { it.cancel() } }
                throw error
            }
            if (next.isSuccess) {
                jobs.forEach { it.cancel() }
                synchronized(calls) { calls.forEach { it.cancel() } }
                return@coroutineScope next.getOrThrow()
            }
            if (error is java.io.IOException) failure = error
        }
        throw failure ?: java.io.IOException("No reachable Jarvis endpoint")
    }

    private fun originRequest(
        address: String,
        path: String,
        method: String,
        body: ByteArray?,
        authenticated: Boolean,
        contentType: String,
        filename: String?,
        extraHeaders: Map<String, String>,
    ): Request {
        val request = Request.Builder().url("${TransportPolicy.origin(address)}/api/companion$path")
        if (authenticated) request.header("Authorization", "Bearer $token").header("X-Jarvis-Device", deviceId)
        if (filename != null) request.header("X-Filename", filename.filter { it.code in 32..126 }.take(200))
        extraHeaders.forEach { (key, value) -> request.header(key, value) }
        request.method(method, if (method == "GET") null else (body ?: ByteArray(0)).toRequestBody(contentType.toMediaType()))
        return request.build()
    }

    private fun callOrigin(
        client: OkHttpClient,
        address: String,
        path: String,
        method: String,
        body: ByteArray?,
        authenticated: Boolean,
        contentType: String,
        filename: String?,
        extraHeaders: Map<String, String>,
    ): ByteArray = readOrigin(
        client.newCall(originRequest(address, path, method, body, authenticated, contentType, filename, extraHeaders)),
        address,
    )

    private fun readOrigin(call: okhttp3.Call, address: String): ByteArray {
        call.execute().use { response ->
            val result = response.body?.bytes() ?: ByteArray(0)
            if (!response.isSuccessful) {
                if (response.code == 401) {
                    token = ""
                    expiresAt = 0
                }
                val reason = runCatching { JSONObject(result.toString(Charsets.UTF_8)).optString("detail") }.getOrDefault("")
                throw ApiException(response.code, reason.ifEmpty { "Jarvis returned ${response.code}" })
            }
            noteReachable(address)
            return result
        }
    }

    companion object {
        fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
