package com.jarvis.companion

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
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
    private val lifetime = CoroutineScope(Dispatchers.IO + SupervisorJob())

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

    suspend fun downloadSelected(onProgress: (Int) -> Unit = {}) = withContext(Dispatchers.IO) {
        val pack = selectedPack() ?: error("No pack selected")
        require(pack.url.isNotBlank()) { "ANZU desktop has not published a download URL for this pack yet" }
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
            val digest = digestCache.digestOf(partial)
            if (!digest.equals(pack.sha256, ignoreCase = true)) {
                digestCache.invalidate(partial)
                partial.delete()
                statusRef.set(CompanionPackStatus.ERROR)
                errorRef.set("Download checksum mismatch")
                error("Download checksum mismatch")
            }
        }
        partial.renameTo(target)
        digestCache.invalidate(partial)
        if (pack.sha256.isNotBlank()) digestCache.remember(target, pack.sha256)
        statusRef.set(CompanionPackStatus.READY)
        progressRef.set(100)
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
        val cancelWatch = CoroutineScope(Dispatchers.Default).launch {
            try {
                while (parentJob.isActive) delay(8)
            } finally {
                engine.requestCancel()
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
            val toRun = if (plan.sectioned && plan.sections.isNotEmpty()) {
                var summaries = summarizeSections(
                    sections = plan.sections,
                    maxTokens = maxTokens.coerceAtMost(plan.summaryMaxTokens),
                )
                var finalPrompt = OfflinePromptPlanner.finalPromptFromSummaries(
                    plan.history,
                    latest.ifBlank { prompt },
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
                        latest.ifBlank { prompt },
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
            GenerateResult(truncated = outcome.truncated, sectioned = sectioned)
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

    fun requestCancelAndUnloadAsync() {
        engine.requestCancel()
        lifetime.launch {
            withContext(NonCancellable) { unload() }
        }
    }

}
