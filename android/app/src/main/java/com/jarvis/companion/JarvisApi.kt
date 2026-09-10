package com.jarvis.companion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.Dispatchers
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

    fun configure(url: String, publicPin: String) {
        val address = TransportPolicy.origin(url)
        require(publicPin.matches(Regex("[a-fA-F0-9]{64}"))) { "Server fingerprint must contain 64 hexadecimal characters" }
        val changed = pin != publicPin.lowercase()
        endpoint = address
        pin = publicPin.lowercase()
        if (changed) { deviceId = ""; token = ""; expiresAt = 0; endpoints = emptyList(); cachedClient = null }
        preferred = ""; preferredAt = 0
        endpoints = (listOf(endpoint) + endpoints).distinct().take(8)
        prefs.edit().putString("endpoint", endpoint).putString("pin", pin).putString("device", deviceId).putString("endpoints", JSONArray(endpoints).toString()).apply()
    }

    suspend fun refreshEndpoints() {
        val settings = json("/connection")
        if (settings.optString("server_pin") != pin) return
        val values = settings.optJSONArray("endpoints") ?: return
        val addresses = (0 until values.length()).map { TransportPolicy.origin(values.getString(it)) }.distinct().take(8)
        if (addresses.isNotEmpty()) {
            endpoints = addresses
            prefs.edit().putString("endpoints", JSONArray(addresses).toString()).apply()
        }
    }

    private fun publicKey() = Base64.encodeToString(keys.getCertificate(keyAlias).publicKey.encoded, Base64.NO_WRAP)
    fun fingerprint() = sha256(keys.getCertificate(keyAlias).publicKey.encoded)

    suspend fun pair(invite: String): JSONObject {
        val result = raw("/enroll", "POST", JSONObject().put("invitation", invite).put("public_key", publicKey()).put("name", android.os.Build.MODEL).toString().toByteArray(), false)
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
            update("jarvis-mobile-v1\n$deviceId\n${challenge.getString("challenge")}".toByteArray())
            Base64.encodeToString(sign(), Base64.NO_WRAP)
        }
        val result = JSONObject(raw("/session", "POST", JSONObject().put("device_id", deviceId).put("signature", proof).toString().toByteArray(), false).toString(Charsets.UTF_8))
        token = result.getString("access_token")
        expiresAt = System.currentTimeMillis() + (result.getLong("expires_in") - 30) * 1000
    }

    suspend fun json(path: String, method: String = "GET", body: JSONObject? = null): JSONObject =
        JSONObject(raw(path, method, body?.toString()?.toByteArray()).toString(Charsets.UTF_8))
    suspend fun array(path: String): JSONArray = JSONArray(raw(path).toString(Charsets.UTF_8))

    suspend fun raw(path: String, method: String = "GET", body: ByteArray? = null,
                    authenticated: Boolean = true, contentType: String = "application/json", filename: String? = null): ByteArray = withContext(Dispatchers.IO) {
        if (authenticated) session()
        require(endpoint.startsWith("https://") && pin.length == 64) { "Set the Jarvis endpoint and server fingerprint" }
        val expectedPin = pin
        val client = cachedClient?.takeIf { it.first == expectedPin }?.second ?: run {
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
        val requestId = if (path == "/messages" && body != null) runCatching { JSONObject(body.toString(Charsets.UTF_8)).optString("request_id") }.getOrNull() else null
        val retry = TransportPolicy.replayable(method, path, requestId)
        val recent = preferred.takeIf { System.currentTimeMillis() - preferredAt < 60000 }
        val addresses = (listOfNotNull(recent) + endpoints + endpoint).filter { it.isNotBlank() }.distinct().let { if (retry) it else it.take(1) }
        var failure: java.io.IOException? = null
        for (address in addresses) {
        val request = Request.Builder().url("${TransportPolicy.origin(address)}/api/companion$path")
        if (authenticated) request.header("Authorization", "Bearer $token").header("X-Jarvis-Device", deviceId)
        if (filename != null) request.header("X-Filename", filename.filter { it.code in 32..126 }.take(200))
        request.method(method, if (method == "GET") null else (body ?: ByteArray(0)).toRequestBody(contentType.toMediaType()))
        try { client.newCall(request.build()).execute().use { response ->
            val result = response.body?.bytes() ?: ByteArray(0)
            if (!response.isSuccessful) {
                if (response.code == 401) { token = ""; expiresAt = 0 }
                val reason = runCatching { JSONObject(result.toString(Charsets.UTF_8)).optString("detail") }.getOrDefault("")
                throw ApiException(response.code, reason.ifEmpty { "Jarvis returned ${response.code}" })
            }
            preferred = address; preferredAt = System.currentTimeMillis()
            return@withContext result
        } } catch (error: javax.net.ssl.SSLException) { throw error }
        catch (error: java.io.IOException) { failure = error }
        }
        throw failure ?: java.io.IOException("No reachable Jarvis endpoint")
    }

    companion object {
        fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
