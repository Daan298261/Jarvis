package com.jarvis.companion

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Pack lifecycle: missing / downloading / ready / running / error */
class CompanionPackManager(
    context: Context,
    val engine: LocalInferenceEngine = LlamaCppInferenceEngine(),
) {
    private val app = context.applicationContext
    private val prefs = app.getSharedPreferences("companion_pack", Context.MODE_PRIVATE)
    private val packDir = File(app.filesDir, "model-packs").apply { mkdirs() }
    private val client = OkHttpClient.Builder().connectTimeout(30, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS).build()
    private val statusRef = AtomicReference(CompanionPackStatus.MISSING)
    private val progressRef = AtomicReference(0)
    private val errorRef = AtomicReference("")
    private var catalog: List<CompanionPack> = CompanionPackCatalog.builtIn

    fun selectedPackId(): String = prefs.getString("selected_pack_id", CompanionPackCatalog.builtIn.first().id) ?: CompanionPackCatalog.builtIn.first().id

    fun selectPack(id: String) {
        prefs.edit().putString("selected_pack_id", id).apply()
    }

    fun updateCatalog(leader: JSONObject?) {
        catalog = CompanionPackCatalog.merge(leader)
    }

    fun catalogJson(): List<JSONObject> = catalog.map { it.toJson() }

    fun status(): String = statusRef.get()

    fun downloadProgress(): Int = progressRef.get()

    fun lastError(): String = errorRef.get()

    fun storageBytes(): Long = packDir.walkTopDown().filter { it.isFile }.map { it.length() }.sum()

    fun selectedPack(): CompanionPack? = catalog.firstOrNull { it.id == selectedPackId() }

    fun packFile(pack: CompanionPack): File = File(packDir, pack.filename)

    fun isPackReady(): Boolean {
        val pack = selectedPack() ?: return false
        val file = packFile(pack)
        return file.isFile && file.length() > 0 && statusRef.get() in setOf(CompanionPackStatus.READY, CompanionPackStatus.RUNNING)
    }

    suspend fun refreshStatus() = withContext(Dispatchers.IO) {
        val pack = selectedPack()
        if (pack == null) {
            statusRef.set(CompanionPackStatus.ERROR)
            errorRef.set("No companion pack selected")
            return@withContext
        }
        val file = packFile(pack)
        if (!file.isFile || file.length() == 0L) {
            statusRef.set(CompanionPackStatus.MISSING)
            errorRef.set("")
            return@withContext
        }
        if (pack.sha256.isNotBlank()) {
            val digest = sha256(file)
            if (!digest.equals(pack.sha256, ignoreCase = true)) {
                statusRef.set(CompanionPackStatus.ERROR)
                errorRef.set("Pack checksum mismatch — delete and download again")
                return@withContext
            }
        }
        statusRef.set(CompanionPackStatus.READY)
        errorRef.set("")
    }

    suspend fun downloadSelected(onProgress: (Int) -> Unit = {}) = withContext(Dispatchers.IO) {
        val pack = selectedPack() ?: error("No pack selected")
        require(pack.url.isNotBlank()) { "Leader has not published a download URL for this pack yet" }
        DeviceInferenceGuard.blockReason(app, pack)?.let { error(it) }
        statusRef.set(CompanionPackStatus.DOWNLOADING)
        progressRef.set(0)
        errorRef.set("")
        val target = packFile(pack)
        val partial = File(target.parent, "${target.name}.partial")
        partial.delete()
        val request = Request.Builder().url(pack.url).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Download failed (${response.code})")
            val body = response.body ?: error("Empty download body")
            val total = body.contentLength().coerceAtLeast(pack.sizeBytes)
            body.byteStream().use { input ->
                partial.outputStream().use { output ->
                    val buffer = ByteArray(65536)
                    var readTotal = 0L
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        readTotal += count
                        val pct = ((readTotal * 100) / total).toInt().coerceIn(0, 100)
                        progressRef.set(pct)
                        onProgress(pct)
                    }
                }
            }
        }
        if (pack.sha256.isNotBlank()) {
            val digest = sha256(partial)
            if (!digest.equals(pack.sha256, ignoreCase = true)) {
                partial.delete()
                statusRef.set(CompanionPackStatus.ERROR)
                errorRef.set("Download checksum mismatch")
                error("Download checksum mismatch")
            }
        }
        partial.renameTo(target)
        statusRef.set(CompanionPackStatus.READY)
        progressRef.set(100)
    }

    fun deleteSelected() {
        val pack = selectedPack()
        engine.unload()
        if (pack != null) packFile(pack).delete()
        statusRef.set(CompanionPackStatus.MISSING)
        errorRef.set("")
        progressRef.set(0)
    }

    suspend fun generate(prompt: String, maxTokens: Int = 256, onToken: (String) -> Unit): String {
        val pack = selectedPack() ?: error("No pack selected")
        DeviceInferenceGuard.blockReason(app, pack)?.let { error(it) }
        val path = packFile(pack)
        if (!path.isFile) error("Install the companion model pack first")
        statusRef.set(CompanionPackStatus.RUNNING)
        val loadError = engine.load(path.absolutePath, 2048)
        if (loadError != null) {
            statusRef.set(CompanionPackStatus.ERROR)
            errorRef.set(loadError)
            error(loadError)
        }
        val genError = engine.generate(prompt, maxTokens, onToken)
        statusRef.set(CompanionPackStatus.READY)
        if (genError != null) {
            statusRef.set(CompanionPackStatus.ERROR)
            errorRef.set(genError)
            error(genError)
        }
        return ""
    }

    fun unload() {
        engine.unload()
        if (statusRef.get() == CompanionPackStatus.RUNNING) statusRef.set(CompanionPackStatus.READY)
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(65536)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
