package com.jarvis.companion

import android.content.Context
import android.os.StatFs
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

enum class OffGridStatus { MISSING, DOWNLOADING, READY, ERROR }

data class OffGridItemState(
    val status: OffGridStatus = OffGridStatus.MISSING,
    val progress: Int = 0,
    val error: String? = null,
    /** Bytes already on disk from an interrupted/cancelled download (resumed next time). */
    val partialBytes: Long = 0L,
    /** Bytes on disk for a READY item (ZIM file length, or MapLibre's completed resource size). */
    val diskBytes: Long = 0L,
)

/** Map regions live in MapLibre's offline DB; abstracted so the manager is testable on the JVM. */
interface OffGridMapStore {
    /** Current state of every catalog region (missing if never created). */
    suspend fun states(items: List<OffGridItem>): Map<String, OffGridItemState>
    /** Starts or resumes downloading; [onState] is called on every status change until complete or error. */
    suspend fun download(item: OffGridItem, onState: (OffGridItemState) -> Unit)
    suspend fun pause(item: OffGridItem)
    suspend fun delete(item: OffGridItem)
}

/**
 * RFC-0216 S2 off-grid content lifecycle. ZIMs use the same resumable download + SHA-256 rules as the
 * companion model packs ([PackDownloadPlan], [TransientRetry], [VerifiedDigestCache]); map regions go
 * through MapLibre's offline manager. Nothing is ever reported READY without verification.
 */
class OffGridContentManager(
    private val root: File,
    private val digestCache: VerifiedDigestCache,
    private val mapStore: OffGridMapStore,
    val catalog: List<OffGridItem> = OffGridContentCatalog.builtIn,
    private val client: OkHttpClient = defaultClient(),
    private val freeBytes: (File) -> Long = { StatFs(it.absolutePath).availableBytes },
    private val retrySleep: suspend (Long) -> Unit = { kotlinx.coroutines.delay(it) },
    /** Production catalogs must be HTTPS; tests against a local MockWebServer pass "http://". */
    urlScheme: String = "https://",
) {
    private val mutable = MutableStateFlow<Map<String, OffGridItemState>>(catalog.associate { it.id to OffGridItemState() })
    val state: StateFlow<Map<String, OffGridItemState>> = mutable
    private val locks = ConcurrentHashMap<String, Mutex>()

    init {
        OffGridContentCatalog.validate(catalog, urlScheme)
        root.mkdirs()
    }

    fun item(id: String): OffGridItem = catalog.firstOrNull { it.id == id } ?: error("Unknown off-grid item: $id")
    fun file(item: OffGridItem): File = File(root, item.fileName)
    private fun partial(item: OffGridItem): File = File(root, "${item.fileName}.partial")
    private fun set(id: String, s: OffGridItemState) = mutable.update { it + (id to s) }
    fun stateOf(id: String): OffGridItemState = mutable.value[id] ?: OffGridItemState()
    fun freeSpace(): Long = freeBytes(root)
    fun partialBytes(items: Collection<OffGridItem>): Long = items.filter { !it.isMap }.sumOf { partial(it).length() }

    /** Re-reads disk + MapLibre state. A ZIM is READY only when its bytes hash to the pinned SHA-256. */
    suspend fun refresh() = withContext(Dispatchers.IO) {
        for (item in catalog.filter { !it.isMap }) {
            if (stateOf(item.id).status == OffGridStatus.DOWNLOADING) continue
            val f = file(item)
            val s = when {
                f.isFile && digestCache.digestOf(f).equals(item.sha256, ignoreCase = true) -> OffGridItemState(OffGridStatus.READY, 100, diskBytes = f.length())
                f.isFile -> OffGridItemState(OffGridStatus.ERROR, error = "${item.title} failed verification. Delete it and download again.")
                else -> OffGridItemState(partialBytes = partial(item).length(),
                    progress = progressOf(partial(item).length(), item.sizeBytes))
            }
            set(item.id, s)
        }
        val maps = catalog.filter { it.isMap }
        mapStore.states(maps).forEach { (id, s) -> if (stateOf(id).status != OffGridStatus.DOWNLOADING) set(id, s) }
    }

    /** Downloads one picked item. Cancellation keeps the partial for resume and never leaves READY. */
    suspend fun download(id: String) {
        val item = item(id)
        val lock = locks.getOrPut(id) { Mutex() }
        if (!lock.tryLock()) return
        try {
            if (item.isMap) downloadMap(item) else downloadZim(item)
        } finally {
            lock.unlock()
        }
    }

    private suspend fun downloadMap(item: OffGridItem) {
        set(item.id, OffGridItemState(OffGridStatus.DOWNLOADING))
        try {
            mapStore.download(item) { set(item.id, it) }
        } catch (e: CancellationException) {
            withContext(kotlinx.coroutines.NonCancellable) { mapStore.pause(item) }
            set(item.id, stateOf(item.id).copy(status = OffGridStatus.MISSING, error = null))
            throw e
        }
    }

    private suspend fun downloadZim(item: OffGridItem) = withContext(Dispatchers.IO) {
        val target = file(item)
        val part = partial(item)
        val offset = PackDownloadPlan.resumeFrom(part.length(), item.sizeBytes)
        if (offset == 0L && !PackDownloadPlan.partialIsComplete(part.length(), item.sizeBytes)) part.delete()
        OffGridSelection.storageBlockReason(freeBytes(root), listOf(item), part.length())?.let { reason ->
            set(item.id, OffGridItemState(OffGridStatus.ERROR, error = reason))
            return@withContext
        }
        set(item.id, OffGridItemState(OffGridStatus.DOWNLOADING, progressOf(part.length(), item.sizeBytes)))
        try {
            TransientRetry.run(
                attempts = PackDownloadPlan.DOWNLOAD_ATTEMPTS,
                baseDelayMs = PackDownloadPlan.RETRY_BASE_DELAY_MS,
                maxDelayMs = PackDownloadPlan.RETRY_MAX_DELAY_MS,
                sleep = retrySleep,
            ) { downloadOnce(item, part) }
        } catch (e: CancellationException) {
            set(item.id, OffGridItemState(OffGridStatus.MISSING, progressOf(part.length(), item.sizeBytes), partialBytes = part.length()))
            throw e
        } catch (e: IOException) {
            set(item.id, OffGridItemState(OffGridStatus.ERROR, progressOf(part.length(), item.sizeBytes),
                "Download interrupted (${e.message}). Tap Retry to resume.", part.length()))
            return@withContext
        } catch (e: IllegalStateException) {
            set(item.id, OffGridItemState(OffGridStatus.ERROR, error = e.message, partialBytes = part.length()))
            return@withContext
        }
        val digest = digestCache.digestOf(part)
        if (!digest.equals(item.sha256, ignoreCase = true)) {
            digestCache.invalidate(part)
            part.delete()
            set(item.id, OffGridItemState(OffGridStatus.ERROR, error = "${item.title}: checksum mismatch. The damaged file was removed; tap Retry."))
            return@withContext
        }
        digestCache.invalidate(part)
        target.delete()
        if (!part.renameTo(target)) {
            set(item.id, OffGridItemState(OffGridStatus.ERROR, error = "Could not move ${item.title} into place. Tap Retry."))
            return@withContext
        }
        digestCache.remember(target, item.sha256)
        set(item.id, OffGridItemState(OffGridStatus.READY, 100, diskBytes = target.length()))
    }

    private suspend fun downloadOnce(item: OffGridItem, part: File) {
        if (PackDownloadPlan.partialIsComplete(part.length(), item.sizeBytes)) return
        var offset = PackDownloadPlan.resumeFrom(part.length(), item.sizeBytes)
        val builder = Request.Builder().url(item.url).get()
        if (offset > 0L) builder.header("Range", "bytes=$offset-")
        client.newCall(builder.build()).execute().use { response ->
            if (response.code >= 500 || response.code == 429) throw IOException("server returned ${response.code}")
            if (!response.isSuccessful) error("${item.title}: download failed (HTTP ${response.code})")
            val append = PackDownloadPlan.appendToPartial(offset, response.code)
            if (!append) offset = 0L
            val body = response.body ?: throw IOException("empty response")
            body.byteStream().use { input ->
                FileOutputStream(part, append).use { output ->
                    val buffer = ByteArray(256 * 1024)
                    var read = offset
                    var lastPct = -1
                    while (true) {
                        if (!coroutineContext.isActive) throw CancellationException("cancelled; partial kept for resume")
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n)
                        read += n
                        val pct = progressOf(read, item.sizeBytes)
                        if (pct != lastPct) { lastPct = pct; set(item.id, OffGridItemState(OffGridStatus.DOWNLOADING, pct, partialBytes = read)) }
                    }
                }
            }
        }
        if (part.length() < item.sizeBytes) throw IOException("ended early at ${part.length()} of ${item.sizeBytes} bytes")
        if (part.length() > item.sizeBytes) {
            part.delete()
            error("${item.title}: server sent more bytes than the pinned size. Tap Retry.")
        }
    }

    suspend fun delete(id: String) = withContext(Dispatchers.IO) {
        val item = item(id)
        if (item.isMap) mapStore.delete(item) else {
            digestCache.invalidate(file(item)); file(item).delete(); partial(item).delete()
        }
        set(id, OffGridItemState())
    }

    /** Directory holding ZIMs and their `.partial` files; read by the S5 inventory. */
    fun storageDir(): File = root

    /**
     * Deletes one file in [storageDir] that is not the current catalogue file of any item (an older ZIM
     * version or an orphaned partial). Catalogue items go through [delete].
     */
    suspend fun deleteStrayFile(name: String) = withContext(Dispatchers.IO) {
        val f = File(root, name)
        require(PackDownloadPlan.isDirectChild(root, name)) { "Not an off-grid file: $name" }
        require(catalog.none { it.fileName == name }) { "$name is a catalogue item; delete it by id" }
        digestCache.invalidate(f)
        if (f.exists() && !f.delete()) error("Could not delete $name")
    }

    /** Fail closed: returns the verified ZIM file or throws with owner-facing copy. */
    suspend fun verifiedZim(id: String): File = withContext(Dispatchers.IO) {
        val item = item(id)
        require(!item.isMap) { "${item.title} is a map" }
        val f = file(item)
        if (!f.isFile) error("${item.title} is not downloaded. Open Off-grid content and download it first.")
        if (!digestCache.digestOf(f).equals(item.sha256, ignoreCase = true)) {
            set(id, OffGridItemState(OffGridStatus.ERROR, error = "${item.title} failed verification. Delete it and download again."))
            error("${item.title} failed verification. Delete it and download again.")
        }
        f
    }

    companion object {
        fun progressOf(read: Long, total: Long): Int = if (total <= 0) 0 else ((read * 100) / total).toInt().coerceIn(0, 100)

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .build()

        fun storageRoot(context: Context): File =
            File(context.getExternalFilesDir(null) ?: context.filesDir, "offgrid")
    }
}
