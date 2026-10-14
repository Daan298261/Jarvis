package com.jarvis.companion

import android.content.Context
import android.content.SharedPreferences
import android.os.StatFs
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.coroutineContext

private const val TAG = "CompanionPackManager"

fun interface FileHasher {
    fun hash(file: File): String
}

/**
 * SHA-256 cache keyed by (absolute path, length, lastModified).
 * [matchesExpected] is O(1) and never reads file contents — safe on the main thread.
 * [digestOf] reads the file and must run off the main thread.
 */
class VerifiedDigestCache(
    private val hasher: FileHasher = FileHasher { defaultFileSha256(it) },
    private val persist: SharedPreferences? = null,
) {
    data class Entry(val length: Long, val lastModified: Long, val digest: String)

    private val lock = Any()
    private val memory = LinkedHashMap<String, Entry>()
    private val hashCalls = AtomicInteger(0)

    fun hashCallCount(): Int = hashCalls.get()

    fun matchesExpected(file: File, expected: String): Boolean {
        if (expected.isBlank() || !file.isFile || file.length() == 0L) return false
        val hit = lookup(file) ?: return false
        return hit.digest.equals(expected, ignoreCase = true)
    }

    fun digestOf(file: File): String {
        lookup(file)?.let { return it.digest }
        hashCalls.incrementAndGet()
        val digest = hasher.hash(file)
        remember(file, digest)
        return digest
    }

    fun remember(file: File, digest: String) {
        val entry = Entry(file.length(), file.lastModified(), digest)
        synchronized(lock) { memory[file.absolutePath] = entry }
        persist?.edit()?.putString(persistKey(file), serialize(entry))?.apply()
    }

    fun invalidate(file: File) {
        synchronized(lock) { memory.remove(file.absolutePath) }
        persist?.edit()?.remove(persistKey(file))?.apply()
    }

    private fun lookup(file: File): Entry? {
        if (!file.isFile) return null
        val length = file.length()
        val mtime = file.lastModified()
        val path = file.absolutePath
        synchronized(lock) {
            val mem = memory[path]
            if (mem != null && mem.length == length && mem.lastModified == mtime) return mem
        }
        val raw = persist?.getString(persistKey(file), null) ?: return null
        val stored = deserialize(raw) ?: return null
        if (stored.length != length || stored.lastModified != mtime) return null
        synchronized(lock) { memory[path] = stored }
        return stored
    }

    private fun persistKey(file: File) = "digest:${file.absolutePath}"

    private fun serialize(entry: Entry) = "${entry.length}|${entry.lastModified}|${entry.digest}"

    private fun deserialize(raw: String): Entry? {
        val parts = raw.split("|", limit = 3)
        if (parts.size != 3) return null
        val length = parts[0].toLongOrNull() ?: return null
        val mtime = parts[1].toLongOrNull() ?: return null
        if (parts[2].length != 64) return null
        return Entry(length, mtime, parts[2])
    }
}

fun defaultFileSha256(file: File): String {
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

/** Pack lifecycle: missing / downloading / ready / running / error */
class CompanionPackManager(
    context: Context,
    val engine: LocalInferenceEngine = LlamaCppInferenceEngine(),
    digestCache: VerifiedDigestCache? = null,
) {
    private val app = context.applicationContext
    val digestCache: VerifiedDigestCache = digestCache ?: VerifiedDigestCache(
        persist = context.applicationContext.getSharedPreferences("companion_pack_digest", Context.MODE_PRIVATE),
    )
    private val prefs = app.getSharedPreferences("companion_pack", Context.MODE_PRIVATE)
    private val packDir = File(app.filesDir, "model-packs").apply { mkdirs() }
    private val client = OkHttpClient.Builder().connectTimeout(30, TimeUnit.SECONDS).readTimeout(120, TimeUnit.SECONDS).build()
    private val statusRef = AtomicReference(CompanionPackStatus.MISSING)
    private val progressRef = AtomicReference(0)
    private val errorRef = AtomicReference("")
    private var catalog: List<CompanionPack> = CompanionPackCatalog.builtIn
    private val llamaDispatcher = Dispatchers.IO.limitedParallelism(1)
    private val activeDownloads: MutableSet<String> = java.util.concurrent.ConcurrentHashMap.newKeySet()

    /** Pack ids with a download running (from any screen). */
    fun downloadingPackIds(): Set<String> = activeDownloads.toSet()

    fun selectedPackId(): String = prefs.getString("selected_pack_id", CompanionPackCatalog.builtIn.first().id) ?: CompanionPackCatalog.builtIn.first().id

    fun selectPack(id: String) {
        prefs.edit().putString("selected_pack_id", id).apply()
    }

    fun updateCatalog(leader: JSONObject?) {
        catalog = CompanionPackCatalog.merge(leader) + importedPacks()
    }

    fun catalogJson(): List<JSONObject> = catalog.map { it.toJson() }

    private fun importedPacks(): List<CompanionPack> = runCatching {
        org.json.JSONArray(prefs.getString("imports", "[]")).objects().map {
            CompanionPack(it.getString("id"), it.getString("label"), it.getString("filename"),
                it.getLong("size_bytes"), it.getInt("min_ram_mb"), it.getString("sha256"), "", false)
        }
    }.getOrDefault(emptyList())

    init { catalog = catalog + importedPacks() }

    suspend fun importGguf(uri: android.net.Uri) = withContext(Dispatchers.IO) {
        val id = "import-" + java.util.UUID.randomUUID().toString()
        val target = File(packDir, "$id.gguf")
        try {
            app.contentResolver.openInputStream(uri)?.use { input ->
                val header = ByteArray(4)
                require(input.read(header) == 4 && header.contentEquals(byteArrayOf(71, 71, 85, 70))) { "Choose a GGUF model file" }
                target.outputStream().use { output ->
                    output.write(header)
                    val buffer = ByteArray(65536)
                    var size = 4L
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        size += count
                        require(size <= 4L * 1024 * 1024 * 1024) { "Choose a phone-sized GGUF (up to 4 GiB)" }
                        output.write(buffer, 0, count)
                    }
                }
            } ?: error("Cannot read selected file")
            val digest = defaultFileSha256(target)
            val ram = ((target.length() / (1024 * 1024)) + 768).toInt().coerceAtLeast(1024)
            val pack = CompanionPack(id, "Imported GGUF (${target.length() / (1024 * 1024)} MiB)", target.name,
                target.length(), ram, digest, "", false)
            val imports = importedPacks() + pack
            val array = org.json.JSONArray()
            imports.forEach { array.put(it.toJson()) }
            check(prefs.edit().putString("imports", array.toString()).commit()) { "Could not save imported model" }
            catalog = catalog.filterNot { it.id.startsWith("import-") } + imports
            digestCache.remember(target, digest)
            selectPack(id)
            refreshStatus()
        } catch (error: Exception) {
            target.delete()
            throw error
        }
    }

    fun status(): String = statusRef.get()

    fun downloadProgress(): Int = progressRef.get()

    fun lastError(): String = errorRef.get()

    fun storageBytes(): Long = packDir.walkTopDown().filter { it.isFile }.map { it.length() }.sum()

    fun selectedPack(): CompanionPack? = catalog.firstOrNull { it.id == selectedPackId() }

    /** Current (Leader-merged) catalogue; read by the RFC-0216 S5 downloaded-content inventory. */
    fun catalog(): List<CompanionPack> = catalog

    /** App-private directory holding model packs (and their `.partial` / `.importing` files). */
    fun packRoot(): File = packDir

    /**
     * Deletes one file from [packRoot] by name (installed, retired, partial or import temp). The engine
     * is unloaded first so a mapped model is released; status falls back to MISSING when the selected
     * pack is gone, so chat routing fails closed.
     */
    suspend fun deleteInstalledFile(name: String) = withContext(llamaDispatcher) {
        val file = File(packDir, name)
        require(PackDownloadPlan.isDirectChild(packDir, name)) { "Not a model pack file: $name" }
        check(activeDownloads.isEmpty()) { "A model download is running; wait for it to finish or cancel it first" }
        engine.unload()
        digestCache.invalidate(file)
        if (file.exists() && !file.delete()) error("Could not delete $name")
        refreshStatus()
        progressRef.set(0)
    }

    fun packFile(pack: CompanionPack): File = File(packDir, pack.filename)

    fun packCanLoad(pack: CompanionPack): Boolean {
        val file = packFile(pack)
        if (!file.isFile || file.length() == 0L) return false
        if (pack.sha256.isNotBlank() && !digestCache.matchesExpected(file, pack.sha256)) return false
        return DeviceInferenceGuard.blockReason(app, pack) == null
    }

    fun resolveOfflinePack(): CompanionPack? =
        CompanionPackCatalog.resolveOfflinePack(catalog, selectedPackId(), ::packCanLoad)

    fun isPackReady(): Boolean {
        if (resolveOfflinePack() != null) return true
        val pack = selectedPack() ?: return false
        val file = packFile(pack)
        return file.isFile && file.length() > 0 && statusRef.get() in setOf(CompanionPackStatus.READY, CompanionPackStatus.RUNNING)
    }

    suspend fun refreshStatus() = withContext(Dispatchers.IO) {
        // A running download of the selected pack owns the status; a refresh must not overwrite it.
        if (selectedPackId() in activeDownloads) return@withContext
        val fallback = resolveOfflinePack()
        if (fallback != null) {
            statusRef.set(CompanionPackStatus.READY)
            errorRef.set("")
            return@withContext
        }
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
            val digest = digestCache.digestOf(file)
            if (!digest.equals(pack.sha256, ignoreCase = true)) {
                digestCache.invalidate(file)
                statusRef.set(CompanionPackStatus.ERROR)
                errorRef.set("Pack checksum mismatch — delete and download again")
                return@withContext
            }
        }
        DeviceInferenceGuard.blockReason(app, pack)?.let { reason ->
            statusRef.set(CompanionPackStatus.ERROR)
            errorRef.set(reason)
            return@withContext
        }
        statusRef.set(CompanionPackStatus.READY)
        errorRef.set("")
    }

    suspend fun downloadSelected(onProgress: (Int) -> Unit = {}) =
        downloadPack(selectedPack() ?: error("No pack selected"), onProgress)

    /**
     * Downloads [pack] into a `.partial` and only replaces the installed file after the pinned SHA-256
     * verifies, so a failed update never removes the last good copy. Status reflects the selected pack
     * again afterwards when [pack] is not the selected one.
     */
    suspend fun downloadPack(pack: CompanionPack, onProgress: (Int) -> Unit = {}) {
        check(activeDownloads.add(pack.id)) { "${pack.label} is already downloading" }
        try {
            downloadPackInternal(pack, onProgress)
        } finally {
            activeDownloads.remove(pack.id)
            // refreshStatus skips while the selected pack is still downloading elsewhere.
            if (pack.id != selectedPackId()) withContext(kotlinx.coroutines.NonCancellable) { refreshStatus() }
        }
    }

    private suspend fun downloadPackInternal(pack: CompanionPack, onProgress: (Int) -> Unit) = withContext(Dispatchers.IO) {
        require(pack.url.isNotBlank()) { "ANZU desktop has not published a download URL for this pack yet" }
        DeviceInferenceGuard.blockReason(app, pack)?.let { error(it) }
        statusRef.set(CompanionPackStatus.DOWNLOADING)
        progressRef.set(0)
        errorRef.set("")
        val target = packFile(pack)
        val partial = File(target.parent, "${target.name}.partial")
        val offset = PackDownloadPlan.resumeFrom(partial.length(), pack.sizeBytes)
        if (offset == 0L && !PackDownloadPlan.partialIsComplete(partial.length(), pack.sizeBytes)) partial.delete()
        PackDownloadPlan.storageBlockReason(StatFs(packDir.absolutePath).availableBytes, pack.sizeBytes, offset)?.let { reason ->
            statusRef.set(CompanionPackStatus.ERROR)
            errorRef.set(reason)
            error(reason)
        }
        try {
            // Mobile networks drop multi-GB downloads: retry transport errors with backoff,
            // each attempt resuming the .partial from where the last one stopped.
            TransientRetry.run(
                attempts = PackDownloadPlan.DOWNLOAD_ATTEMPTS,
                baseDelayMs = PackDownloadPlan.RETRY_BASE_DELAY_MS,
                maxDelayMs = PackDownloadPlan.RETRY_MAX_DELAY_MS,
                onRetry = { attempt, error ->
                    Log.w(TAG, "Pack download attempt $attempt failed, resuming: ${error.message}")
                    errorRef.set("Connection dropped — resuming download (attempt ${attempt + 1} of ${PackDownloadPlan.DOWNLOAD_ATTEMPTS})")
                },
            ) {
                downloadOnce(pack, partial, onProgress)
            }
        } catch (error: java.io.IOException) {
            statusRef.set(CompanionPackStatus.ERROR)
            errorRef.set("Download interrupted after ${PackDownloadPlan.DOWNLOAD_ATTEMPTS} attempts (${error.message}). Tap Download to resume.")
            throw error
        }
        errorRef.set("")
        if (pack.sha256.isNotBlank()) {
            val digest = digestCache.digestOf(partial)
            if (!digest.equals(pack.sha256, ignoreCase = true)) {
                digestCache.invalidate(partial)
                partial.delete()
                statusRef.set(CompanionPackStatus.ERROR)
                errorRef.set("Download checksum mismatch")
                error("Download checksum mismatch")
            }
        }
        PackDownloadPlan.replaceWithVerified(partial, target)
        digestCache.invalidate(partial)
        if (pack.sha256.isNotBlank()) digestCache.remember(target, pack.sha256)
        statusRef.set(CompanionPackStatus.READY)
        progressRef.set(100)
    }

    /** One HTTP attempt; resumes [partial] with a Range request when bytes are already on disk. */
    private suspend fun downloadOnce(pack: CompanionPack, partial: File, onProgress: (Int) -> Unit) {
        if (PackDownloadPlan.partialIsComplete(partial.length(), pack.sizeBytes)) return
        var offset = PackDownloadPlan.resumeFrom(partial.length(), pack.sizeBytes)
        val builder = Request.Builder().url(pack.url).get()
        if (offset > 0L) builder.header("Range", "bytes=$offset-")
        client.newCall(builder.build()).execute().use { response ->
            // 5xx/429 are transient on the CDN: surface them as IOException so they retry.
            if (response.code >= 500 || response.code == 429) throw java.io.IOException("Download server returned ${response.code}")
            if (!response.isSuccessful) error("Download failed (${response.code})")
            val append = PackDownloadPlan.appendToPartial(offset, response.code)
            if (!append) offset = 0L
            val body = response.body ?: throw java.io.IOException("Empty download body")
            val total = (offset + body.contentLength()).coerceAtLeast(pack.sizeBytes).coerceAtLeast(1L)
            body.byteStream().use { input ->
                java.io.FileOutputStream(partial, append).use { output ->
                    val buffer = ByteArray(65536)
                    var readTotal = offset
                    while (true) {
                        if (!coroutineContext.isActive) throw CancellationException("download cancelled; partial kept for resume")
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
        if (pack.sizeBytes > 0L && partial.length() < pack.sizeBytes) {
            throw java.io.IOException("Download ended early at ${partial.length()} of ${pack.sizeBytes} bytes")
        }
    }

    /**
     * Imports a GGUF the owner picked from storage. The bytes are copied into app storage, hashed, and
     * only kept when they match a catalog model's pinned SHA-256; that model is then selected.
     */
    suspend fun importSideloaded(input: java.io.InputStream, declaredBytes: Long, onProgress: (Int) -> Unit = {}): CompanionPack = withContext(Dispatchers.IO) {
        val maxBytes = (catalog.maxOfOrNull { it.sizeBytes } ?: 0L).coerceAtLeast(1L)
        if (declaredBytes > maxBytes) error(ModelSideload.tooLargeCopy(maxBytes))
        PackDownloadPlan.storageBlockReason(StatFs(packDir.absolutePath).availableBytes, declaredBytes.coerceAtLeast(0L), 0L)?.let { error(it) }
        val temp = File(packDir, "sideload-${System.nanoTime()}.importing")
        statusRef.set(CompanionPackStatus.DOWNLOADING)
        progressRef.set(0)
        errorRef.set("")
        try {
            val copied = ModelSideload.copyAndHash(input, temp, maxBytes, isCancelled = { !coroutineContext.isActive }) { bytes ->
                if (declaredBytes > 0L) {
                    val pct = ((bytes * 100) / declaredBytes).toInt().coerceIn(0, 99)
                    progressRef.set(pct)
                    onProgress(pct)
                }
            }
            if (!copied.ggufHeader) error(ModelSideload.notGgufCopy())
            val pack = ModelSideload.match(copied.digest, copied.bytes, catalog) ?: error(ModelSideload.unknownModelCopy(copied.digest))
            engine.unload()
            val target = packFile(pack)
            digestCache.invalidate(target)
            target.delete()
            if (!temp.renameTo(target)) error("Could not move the model into ANZU storage")
            digestCache.remember(target, pack.sha256)
            selectPack(pack.id)
            progressRef.set(100)
            onProgress(100)
            refreshStatus()
            pack
        } catch (error: Throwable) {
            temp.delete()
            // A rejected file must not mark an already-installed model as broken.
            withContext(kotlinx.coroutines.NonCancellable) { refreshStatus() }
            if (error !is CancellationException) {
                Log.w(TAG, "Model import rejected: ${error.message}")
                errorRef.set(error.message ?: "Model import failed")
            }
            throw error
        }
    }

    fun deleteSelected() {
        val pack = selectedPack()
        engine.unload()
        if (pack != null) {
            val file = packFile(pack)
            digestCache.invalidate(file)
            file.delete()
        }
        statusRef.set(CompanionPackStatus.MISSING)
        errorRef.set("")
        progressRef.set(0)
    }

    suspend fun generate(
        prompt: String,
        maxTokens: Int = DeviceInferenceGuard.BUDGET_CLEAR,
        history: List<org.json.JSONObject> = emptyList(),
        latest: String = "",
        pickedText: String? = null,
        onToken: (String) -> Unit,
    ): GenerateResult = withContext(llamaDispatcher) {
        val pack = resolveOfflinePack() ?: selectedPack() ?: error("No pack selected")
        DeviceInferenceGuard.blockReason(app, pack)?.let { error(it) }
        val path = packFile(pack)
        if (!path.isFile) error("Install the companion model pack first")
        statusRef.set(CompanionPackStatus.RUNNING)
        val nCtx = DeviceInferenceGuard.contextTokens(app, pack)
        val parentJob = coroutineContext[Job]!!
        // Started UNDISPATCHED on Unconfined: the watcher is already suspended in
        // awaitCancellation() before the engine runs, and cancel() resumes it inline on the
        // cancelling thread. A Default-dispatched watcher could be cancelled before it ever ran
        // (its finally then never fires) or wait behind a busy pool, leaving native decode
        // running after the user pressed stop.
        val cancelWatch = launch(Dispatchers.Unconfined, start = CoroutineStart.UNDISPATCHED) {
            try {
                awaitCancellation()
            } finally {
                if (parentJob.isCancelled) engine.requestCancel()
            }
        }
        try {
            val loadError = engine.load(path.absolutePath, nCtx)
            if (loadError != null) {
                statusRef.set(CompanionPackStatus.ERROR)
                errorRef.set(loadError)
                error(loadError)
            }
            if (!coroutineContext.isActive) throw CancellationException("generate cancelled")
            val promptBudget = OfflinePromptPlanner.promptTokenBudget(nCtx, maxTokens)
            val plan = if (latest.isNotEmpty() || !pickedText.isNullOrBlank()) {
                OfflinePromptPlanner.plan(
                    history = history,
                    latest = latest.ifBlank { prompt },
                    pickedText = pickedText,
                    tokenize = { engine.tokenize(it) },
                    promptBudget = promptBudget,
                )
            } else {
                OfflinePromptPlanner.Plan(prompt = prompt, sectioned = false, history = history)
            }
            val sectioned = plan.sectioned
            val latestText = plan.latest.ifBlank { latest.ifBlank { prompt } }
            val toRun = if (plan.sectioned && plan.sections.isNotEmpty()) {
                var summaries = summarizeSections(
                    sections = plan.sections,
                    maxTokens = maxTokens.coerceAtMost(plan.summaryMaxTokens),
                )
                var finalPrompt = OfflinePromptPlanner.finalPromptFromSummaries(
                    plan.history,
                    latestText,
                    summaries,
                )
                var reduceGuard = 0
                while (engine.tokenize(finalPrompt) > promptBudget && summaries.size > 1 && reduceGuard++ < 4) {
                    val merged = OfflinePromptPlanner.mergeAdjacent(summaries)
                    val cap = OfflinePromptPlanner.sectionSummaryMaxTokens(
                        promptBudget,
                        plan.skeletonTokens,
                        merged.size,
                    )
                    summaries = summarizeSections(merged, maxTokens.coerceAtMost(cap))
                    finalPrompt = OfflinePromptPlanner.finalPromptFromSummaries(
                        plan.history,
                        latestText,
                        summaries,
                    )
                }
                finalPrompt
            } else {
                plan.prompt
            }
            if (!coroutineContext.isActive) throw CancellationException("generate cancelled")
            var produced = false
            engine.beginPass()
            val outcome = engine.generate(toRun, maxTokens) { chunk ->
                produced = true
                onToken(chunk)
            }
            if (outcome.cancelled) throw CancellationException("generate cancelled")
            if (!coroutineContext.isActive) throw CancellationException("generate cancelled")
            statusRef.set(CompanionPackStatus.READY)
            outcome.error?.let { failGenerate(it) }
            if (!produced && !outcome.truncated) {
                failGenerate("On-device model returned no tokens")
            }
            GenerateResult(truncated = outcome.truncated, sectioned = sectioned, clipped = plan.clipped)
        } finally {
            cancelWatch.cancel()
        }
    }

    private suspend fun summarizeSections(sections: List<String>, maxTokens: Int): ArrayList<String> {
        val summaries = ArrayList<String>()
        for (section in sections) {
            if (!coroutineContext.isActive) throw CancellationException("generate cancelled")
            engine.beginPass()
            val piece = StringBuilder()
            val outcome = engine.generate(
                OfflinePromptPlanner.summarizeSectionPrompt(section),
                maxTokens,
            ) { piece.append(it) }
            if (outcome.cancelled) throw CancellationException("generate cancelled")
            outcome.error?.let { failGenerate(it) }
            summaries.add(piece.toString().ifBlank { section.take(240) })
        }
        return summaries
    }

    private fun failGenerate(message: String): Nothing {
        statusRef.set(CompanionPackStatus.ERROR)
        errorRef.set(message)
        error(message)
    }

    fun requestCancel() {
        engine.requestCancel()
    }

    fun unload() {
        engine.unload()
        if (statusRef.get() == CompanionPackStatus.RUNNING) statusRef.set(CompanionPackStatus.READY)
    }

}
