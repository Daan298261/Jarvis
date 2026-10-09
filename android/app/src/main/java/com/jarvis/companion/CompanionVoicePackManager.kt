package com.jarvis.companion

import android.content.Context
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.coroutineContext

/**
 * RFC-0140 on-device STT/TTS pack lifecycle.
 * Mirrors [CompanionPackManager]: download + SHA-256 verify into app-private storage; never soft-fail.
 */
class CompanionVoicePackManager(
    context: Context,
    val sttEngine: OnDeviceSttEngine = WhisperCppSttEngine(),
    val ttsEngine: OnDeviceTtsEngine = PocketTtsEngine(),
    digestCache: VerifiedDigestCache? = null,
) {
    private val app = context.applicationContext
    val digestCache: VerifiedDigestCache = digestCache ?: VerifiedDigestCache(
        persist = context.applicationContext.getSharedPreferences("companion_voice_digest", Context.MODE_PRIVATE),
    )
    private val prefs = app.getSharedPreferences("companion_voice_pack", Context.MODE_PRIVATE)
    private val packRoot = File(app.filesDir, "voice-packs").apply { mkdirs() }
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    private val sttStatusRef = AtomicReference(CompanionVoicePackStatus.MISSING)
    private val ttsStatusRef = AtomicReference(CompanionVoicePackStatus.MISSING)
    private val progressRef = AtomicReference(0)
    private val errorRef = AtomicReference("")
    private var catalog: List<CompanionVoicePack> = CompanionVoicePackCatalog.builtIn
    private val sttMutex = Mutex()
    private val ttsMutex = Mutex()

    private fun mutexFor(role: String) = if (role == "stt") sttMutex else ttsMutex

    init {
        CompanionVoicePackCatalog.validateBuiltIn()
        migrateTtsSelection()
    }

    fun selectedSttPackId(): String =
        prefs.getString("selected_stt_pack_id", CompanionVoicePackCatalog.builtIn.first { it.role == "stt" && it.recommended }.id)
            ?: "whisper-tiny-en-cpp"

    fun selectedTtsPackId(): String {
        migrateTtsSelection()
        return prefs.getString("selected_tts_pack_id", CompanionVoicePackCatalog.POCKET_TTS_ID)
            ?: CompanionVoicePackCatalog.POCKET_TTS_ID
    }

    fun selectSttPack(id: String) {
        prefs.edit().putString("selected_stt_pack_id", id).apply()
    }

    fun selectTtsPack(id: String) {
        val pack = catalog.firstOrNull { it.id == id && it.role == "tts" }
        if (pack == null || !CompanionVoicePackCatalog.canSynthesize(pack)) {
            prefs.edit().putString("selected_tts_pack_id", CompanionVoicePackCatalog.POCKET_TTS_ID).apply()
            return
        }
        prefs.edit().putString("selected_tts_pack_id", id).apply()
    }

    fun updateCatalog(leader: JSONObject?) {
        catalog = CompanionVoicePackCatalog.merge(leader)
    }

    fun catalogJson(): List<JSONObject> = catalog.map { it.toJson() }

    fun sttStatus(): String = sttStatusRef.get()
    fun ttsStatus(): String = ttsStatusRef.get()
    fun downloadProgress(): Int = progressRef.get()
    fun lastError(): String = errorRef.get()

    fun storageBytes(): Long = packRoot.walkTopDown().filter { it.isFile }.map { it.length() }.sum()

    fun selectedSttPack(): CompanionVoicePack? = catalog.firstOrNull { it.id == selectedSttPackId() }
    fun selectedTtsPack(): CompanionVoicePack? = catalog.firstOrNull { it.id == selectedTtsPackId() }

    fun packDir(pack: CompanionVoicePack): File = File(packRoot, pack.id).apply { mkdirs() }

    fun artifactFile(pack: CompanionVoicePack, artifact: CompanionVoiceArtifact): File =
        File(packDir(pack), artifact.filename)

    fun isSttReady(): Boolean =
        selectedSttPack()?.let { packReady(it) && sttStatusRef.get() in CompanionVoicePackStatus.USABLE } == true

    fun isTtsReady(): Boolean =
        selectedTtsPack()?.let { packReady(it) && ttsStatusRef.get() in CompanionVoicePackStatus.USABLE } == true

    private fun packReady(pack: CompanionVoicePack): Boolean {
        if (pack.url.isBlank()) return false
        return pack.artifacts.all { art ->
            val file = artifactFile(pack, art)
            file.isFile && file.length() > 0L
        }
    }

    private fun verifyPack(pack: CompanionVoicePack): String? {
        if (pack.url.isBlank()) return "Pack ${pack.id} has no download URL"
        for (art in pack.artifacts) {
            if (art.url.isBlank()) return "Artifact ${art.filename} has no download URL"
            val file = artifactFile(pack, art)
            if (!file.isFile || file.length() == 0L) return null
            if (art.sha256.isNotBlank()) {
                val digest = if (digestCache.matchesExpected(file, art.sha256)) {
                    art.sha256
                } else {
                    digestCache.digestOf(file)
                }
                if (!digest.equals(art.sha256, ignoreCase = true)) {
                    digestCache.invalidate(file)
                    return "Checksum mismatch for ${art.filename} — delete and download again"
                }
            }
        }
        return ""
    }

    suspend fun refreshStatus() = withContext(Dispatchers.IO) {
        migrateTtsSelection()
        pruneRetiredPackDirs()
        refreshOne(selectedSttPack(), sttStatusRef)
        refreshOne(selectedTtsPack(), ttsStatusRef)
    }

    fun pruneRetiredPackDirs() {
        val dirs = packRoot.listFiles() ?: return
        for (dir in dirs) {
            if (!dir.isDirectory) continue
            if (dir.name !in CompanionVoicePackCatalog.RETIRED_PACK_IDS) continue
            dir.walkTopDown().filter { it.isFile }.forEach { digestCache.invalidate(it) }
            dir.deleteRecursively()
        }
    }

    private fun refreshOne(pack: CompanionVoicePack?, statusRef: AtomicReference<String>) {
        if (pack == null) {
            statusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set("No voice pack selected")
            return
        }
        val result = verifyPack(pack)
        when {
            result == null -> {
                statusRef.set(CompanionVoicePackStatus.MISSING)
                if (errorRef.get().isBlank()) errorRef.set("")
            }
            result.isNotEmpty() -> {
                statusRef.set(CompanionVoicePackStatus.ERROR)
                errorRef.set(result)
            }
            else -> {
                statusRef.set(CompanionVoicePackStatus.READY)
                if (errorRef.get().startsWith("Checksum") || errorRef.get().contains(pack.id)) {
                    errorRef.set("")
                }
            }
        }
    }

    suspend fun downloadPack(packId: String, onProgress: (Int) -> Unit = {}) {
        val pack = catalog.firstOrNull { it.id == packId } ?: error("Unknown voice pack: $packId")
        mutexFor(pack.role).withLock {
        withContext(Dispatchers.IO) {
        require(pack.url.isNotBlank()) { "Leader has not published a download URL for voice pack ${pack.id}" }
        DeviceVoiceGuard.blockReason(app, pack)?.let { error(it) }
        if (pack.role == "stt") sttEngine.unload() else ttsEngine.unload()
        val statusRef = if (pack.role == "stt") sttStatusRef else ttsStatusRef
        statusRef.set(CompanionVoicePackStatus.DOWNLOADING)
        progressRef.set(0)
        errorRef.set("")
        val totalBytes = pack.artifacts.sumOf { it.sizeBytes.coerceAtLeast(1L) }
        var readTotal = 0L
        for (art in pack.artifacts) {
            require(art.url.isNotBlank()) { "Empty artifact URL for ${art.filename}" }
            val target = artifactFile(pack, art)
            val partial = File(target.parent, "${target.name}.partial")
            partial.delete()
            val request = Request.Builder().url(art.url).get().build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) error("Download failed for ${art.filename} (${response.code})")
                val body = response.body ?: error("Empty download body for ${art.filename}")
                body.byteStream().use { input ->
                    partial.outputStream().use { output ->
                        val buffer = ByteArray(65536)
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            output.write(buffer, 0, count)
                            readTotal += count
                            val pct = ((readTotal * 100) / totalBytes).toInt().coerceIn(0, 100)
                            progressRef.set(pct)
                            onProgress(pct)
                        }
                    }
                }
            }
            if (art.sha256.isNotBlank()) {
                val digest = digestCache.digestOf(partial)
                if (!digest.equals(art.sha256, ignoreCase = true)) {
                    digestCache.invalidate(partial)
                    partial.delete()
                    statusRef.set(CompanionVoicePackStatus.ERROR)
                    errorRef.set("Download checksum mismatch for ${art.filename}")
                    error("Download checksum mismatch for ${art.filename}")
                }
            }
            partial.renameTo(target)
            digestCache.invalidate(partial)
            if (art.sha256.isNotBlank()) digestCache.remember(target, art.sha256)
        }
        statusRef.set(CompanionVoicePackStatus.READY)
        progressRef.set(100)
        }
        }
    }

    suspend fun downloadSelectedStt(onProgress: (Int) -> Unit = {}) =
        downloadPack(selectedSttPackId(), onProgress)

    suspend fun downloadSelectedTts(onProgress: (Int) -> Unit = {}) =
        downloadPack(selectedTtsPackId(), onProgress)

    suspend fun downloadRecommendedPair(onProgress: (Int) -> Unit = {}) = withContext(Dispatchers.IO) {
        val stt = catalog.firstOrNull { it.role == "stt" && it.recommended } ?: error("No recommended STT pack")
        val tts = catalog.firstOrNull { it.role == "tts" && it.recommended } ?: error("No recommended TTS pack")
        val combined = stt.sizeBytes + tts.sizeBytes
        require(combined <= 500_000_000L) {
            "Recommended voice packs (~${combined / 1_000_000} MB) exceed the 500 MB auto-download gate"
        }
        selectSttPack(stt.id)
        selectTtsPack(tts.id)
        downloadPack(stt.id, onProgress)
        downloadPack(tts.id, onProgress)
    }

    fun deletePack(packId: String) {
        kotlinx.coroutines.runBlocking { deletePackAwait(packId) }
    }

    private fun deletePackUnlocked(packId: String) {
        val pack = catalog.firstOrNull { it.id == packId } ?: return
        if (pack.role == "stt") sttEngine.unload() else ttsEngine.unload()
        pack.artifacts.forEach { digestCache.invalidate(artifactFile(pack, it)) }
        packDir(pack).deleteRecursively()
        val statusRef = if (pack.role == "stt") sttStatusRef else ttsStatusRef
        statusRef.set(CompanionVoicePackStatus.MISSING)
        errorRef.set("")
        progressRef.set(0)
    }

    suspend fun deletePackAwait(packId: String) {
        val pack = catalog.firstOrNull { it.id == packId } ?: return
        mutexFor(pack.role).withLock {
            deletePackUnlocked(packId)
        }
    }

    fun deleteSelectedStt() = deletePack(selectedSttPackId())
    fun deleteSelectedTts() = deletePack(selectedTtsPackId())

    private fun migrateTtsSelection() {
        val stored = prefs.getString("selected_tts_pack_id", null) ?: return
        val valid = catalog.any { it.id == stored && it.role == "tts" && CompanionVoicePackCatalog.canSynthesize(it) }
        if (!valid) {
            prefs.edit().putString("selected_tts_pack_id", CompanionVoicePackCatalog.POCKET_TTS_ID).apply()
        }
    }

    suspend fun transcribePcm16le(pcm: ByteArray, sampleRate: Int = 16_000): String = withContext(Dispatchers.IO) {
        val pack = selectedSttPack() ?: error("No STT pack selected")
        DeviceVoiceGuard.blockReason(app, pack)?.let { error(it) }
        if (!packReady(pack)) error("Install the on-device STT pack first (More → Voice)")
        val verify = verifyPack(pack)
        if (verify == null) error("Install the on-device STT pack first (More → Voice)")
        if (verify.isNotEmpty()) {
            sttStatusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set(verify)
            error(verify)
        }
        sttStatusRef.set(CompanionVoicePackStatus.RUNNING)
        val modelPath = artifactFile(pack, pack.artifacts.first()).absolutePath
        val loadError = sttEngine.load(modelPath, pack.engine)
        if (loadError != null) {
            sttStatusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set(loadError)
            error(loadError)
        }
        val result = sttEngine.transcribe(pcm, sampleRate)
        sttStatusRef.set(CompanionVoicePackStatus.READY)
        result.exceptionOrNull()?.let {
            sttStatusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set(it.message ?: "STT failed")
            error(it.message ?: "STT failed")
        }
        val text = result.getOrNull().orEmpty().trim()
        if (text.isEmpty()) error("On-device STT produced no text — retry or reinstall the pack")
        text
    }

    suspend fun synthesize(text: String): ByteArray = ttsMutex.withLock {
        withContext(Dispatchers.IO) {
        val pack = selectedTtsPack() ?: error("No TTS pack selected")
        DeviceVoiceGuard.blockReason(app, pack)?.let { error(it) }
        if (!packReady(pack)) error("Install the on-device TTS pack first (More → Voice)")
        val verify = verifyPack(pack)
        if (verify == null) error("Install the on-device TTS pack first (More → Voice)")
        if (verify.isNotEmpty()) {
            ttsStatusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set(verify)
            error(verify)
        }
        ttsStatusRef.set(CompanionVoicePackStatus.RUNNING)
        val dir = packDir(pack).absolutePath
        val loadError = ttsEngine.load(dir, pack.engine)
        if (loadError != null) {
            ttsStatusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set(loadError)
            error(loadError)
        }
        val result = ttsEngine.synthesize(text)
        if (!coroutineContext.isActive || result.exceptionOrNull() is CancellationException) {
            ttsStatusRef.set(CompanionVoicePackStatus.READY)
            throw CancellationException("TTS cancelled")
        }
        ttsStatusRef.set(CompanionVoicePackStatus.READY)
        result.exceptionOrNull()?.let {
            ttsStatusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set(it.message ?: "TTS failed")
            error(it.message ?: "TTS failed")
        }
        val audio = result.getOrNull()
        if (audio == null || audio.isEmpty()) error("On-device TTS produced no audio — retry or reinstall the pack")
        if (PocketTtsEngine.isNearSilentPcmWav(audio)) {
            ttsStatusRef.set(CompanionVoicePackStatus.ERROR)
            errorRef.set("On-device TTS returned near-silent audio — refusing soft-fail")
            error("On-device TTS returned near-silent audio — refusing soft-fail")
        }
        audio
        }
    }

    fun unloadIdle() {
        sttEngine.unload()
        ttsEngine.unload()
        if (sttStatusRef.get() == CompanionVoicePackStatus.RUNNING) sttStatusRef.set(CompanionVoicePackStatus.READY)
        if (ttsStatusRef.get() == CompanionVoicePackStatus.RUNNING) ttsStatusRef.set(CompanionVoicePackStatus.READY)
    }

}
