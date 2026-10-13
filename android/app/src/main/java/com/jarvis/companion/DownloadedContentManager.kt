package com.jarvis.companion

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** RFC-0216 S5: the four kinds of offline content the phone can hold. */
enum class ContentKind(val label: String) {
    MODEL("Phone AI models"),
    VOICE("Offline voice packs"),
    MAP("Offline maps"),
    KNOWLEDGE("Knowledge bases (ZIM)"),
}

enum class ContentState {
    /** Installed and matches the catalogue pin. */
    CURRENT,
    /** Installed, but the catalogue now pins a newer version or a different checksum. */
    UPDATE_AVAILABLE,
    /** Installed file does not hash to the pin it was downloaded for. */
    FAILED_VERIFICATION,
    /** Unfinished download (or missing artifacts) still taking space. */
    PARTIAL,
    /** Not in the catalogue any more (or superseded by an installed newer version): delete only. */
    RETIRED,
}

/**
 * One row of the downloaded-content page. [name] is the on-disk name (file, directory or map region id)
 * the owning source uses for update/delete; [updateBytes] is what an update downloads (0 = not updatable).
 */
data class DownloadedEntry(
    val kind: ContentKind,
    val name: String,
    val title: String,
    val bytes: Long,
    val state: ContentState,
    val detail: String,
    val updateBytes: Long = 0L,
    /** A download for this item is running (possibly started from another screen); no actions allowed. */
    val downloading: Boolean = false,
) {
    val key: String get() = "${kind.name}:$name"
    val canUpdate: Boolean get() = updateBytes > 0L && !downloading
}

data class DownloadedInventory(val entries: List<DownloadedEntry>, val errors: List<String>) {
    val totalBytes: Long get() = entries.sumOf { it.bytes }
    fun bytesOf(kind: ContentKind): Long = entries.filter { it.kind == kind }.sumOf { it.bytes }
}

/** One existing pack manager seen through the S5 lens. Download and verification stay in that manager. */
interface DownloadedContentSource {
    val kinds: Set<ContentKind>
    suspend fun entries(): List<DownloadedEntry>
    suspend fun update(entry: DownloadedEntry)
    suspend fun delete(entry: DownloadedEntry)
    /** Non-null when an in-flight download makes [entry] untouchable right now (checked live, not from the row). */
    fun busyReason(entry: DownloadedEntry): String?
}

/**
 * Single read model over [CompanionPackManager], [CompanionVoicePackManager] and [OffGridContentManager].
 * It owns no downloads and no state of its own: every listing re-reads disk through the managers, so the
 * page can never drift from what chat, voice and off-grid actually use. A source that throws is reported
 * in [DownloadedInventory.errors] and the other sections still render.
 */
class DownloadedContentManager(private val sources: List<DownloadedContentSource>) {
    suspend fun inventory(): DownloadedInventory {
        val entries = ArrayList<DownloadedEntry>()
        val errors = ArrayList<String>()
        for (source in sources) {
            try {
                entries += source.entries()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                errors += "${source.kinds.joinToString { it.label }}: ${e.message ?: e.javaClass.simpleName}"
            }
        }
        return DownloadedInventory(entries.sortedWith(compareBy({ it.kind.ordinal }, { -it.bytes })), errors)
    }

    suspend fun update(entry: DownloadedEntry) {
        val source = sourceFor(entry)
        source.busyReason(entry)?.let { error(it) }
        require(entry.updateBytes > 0L) { "${entry.title} has no update in the catalogue" }
        source.update(entry)
    }

    suspend fun delete(entry: DownloadedEntry) {
        val source = sourceFor(entry)
        source.busyReason(entry)?.let { error(it) }
        source.delete(entry)
    }

    private fun sourceFor(entry: DownloadedEntry) =
        sources.firstOrNull { entry.kind in it.kinds } ?: error("No manager for ${entry.kind.label}")

    companion object {
        fun forManagers(models: CompanionPackManager, voice: CompanionVoicePackManager, offGrid: OffGridContentManager?) =
            DownloadedContentManager(listOfNotNull(ModelPackSource(models), VoicePackSource(voice), offGrid?.let(::OffGridSource)))

        internal fun sizeOf(f: File): Long = if (f.isFile) f.length() else f.walkTopDown().filter { it.isFile }.sumOf { it.length() }
    }
}

/** GGUF model packs in [CompanionPackManager.packRoot]. */
class ModelPackSource(private val m: CompanionPackManager) : DownloadedContentSource {
    override val kinds = setOf(ContentKind.MODEL)

    // Any model download shares the engine and status, so every model row waits for it.
    override fun busyReason(entry: DownloadedEntry): String? =
        if (m.downloadingPackIds().isNotEmpty()) "A model download is running; wait for it to finish" else null

    override suspend fun entries(): List<DownloadedEntry> = withContext(Dispatchers.IO) {
        val catalog = m.catalog()
        val active = m.downloadingPackIds()
        val activeFiles = catalog.filter { it.id in active }.flatMap { listOf(it.filename, "${it.filename}.partial") }.toSet()
        m.packRoot().listFiles().orEmpty().filter { it.isFile }.map { f ->
            if (f.name in activeFiles) {
                val pack = catalog.first { f.name.removeSuffix(".partial") == it.filename }
                return@map DownloadedEntry(ContentKind.MODEL, f.name, pack.label, f.length(), ContentState.PARTIAL, "Download in progress", downloading = true)
            }
            val name = f.name
            when {
                name.endsWith(".partial") -> {
                    val pack = catalog.firstOrNull { it.filename == name.removeSuffix(".partial") && it.url.isNotBlank() }
                    DownloadedEntry(ContentKind.MODEL, name, pack?.label ?: name.removeSuffix(".partial"), f.length(), ContentState.PARTIAL,
                        if (pack != null) "Unfinished download — Update resumes it" else "Unfinished download of a model no longer offered",
                        updateBytes = pack?.let { (it.sizeBytes - f.length()).coerceAtLeast(1L) } ?: 0L)
                }
                name.endsWith(".importing") ->
                    DownloadedEntry(ContentKind.MODEL, name, "Interrupted model import", f.length(), ContentState.PARTIAL, "Left over from a cancelled import")
                else -> {
                    val pack = catalog.firstOrNull { it.filename == name }
                    when {
                        pack == null -> DownloadedEntry(ContentKind.MODEL, name, name, f.length(), ContentState.RETIRED, "No longer in the model catalogue")
                        pack.sha256.isBlank() || m.digestCache.matchesExpected(f, pack.sha256) ||
                            m.digestCache.digestOf(f).equals(pack.sha256, ignoreCase = true) ->
                            DownloadedEntry(ContentKind.MODEL, name, pack.label, f.length(), ContentState.CURRENT,
                                if (pack.id == m.selectedPackId()) "In use · verified" else "Verified")
                        else -> DownloadedEntry(ContentKind.MODEL, name, pack.label, f.length(), ContentState.UPDATE_AVAILABLE,
                            "The catalogue pins a different build (checksum changed)",
                            updateBytes = if (pack.url.isNotBlank()) pack.sizeBytes.coerceAtLeast(1L) else 0L)
                    }
                }
            }
        }.map { if (active.isNotEmpty() && !it.downloading) it.copy(downloading = true, detail = "${it.detail} · locked while a model downloads") else it }
    }

    override suspend fun update(entry: DownloadedEntry) {
        val file = entry.name.removeSuffix(".partial")
        val pack = m.catalog().firstOrNull { it.filename == file } ?: error("${entry.title} is no longer in the catalogue")
        m.downloadPack(pack)
    }

    override suspend fun delete(entry: DownloadedEntry) = m.deleteInstalledFile(entry.name)
}

/** STT/TTS pack directories in [CompanionVoicePackManager.packRoot]. */
class VoicePackSource(private val m: CompanionVoicePackManager) : DownloadedContentSource {
    override val kinds = setOf(ContentKind.VOICE)

    override fun busyReason(entry: DownloadedEntry): String? =
        if (entry.name in m.downloadingPackIds()) "${entry.title} is downloading; wait for it to finish" else null

    override suspend fun entries(): List<DownloadedEntry> = withContext(Dispatchers.IO) {
        val active = m.downloadingPackIds()
        m.packRoot().listFiles().orEmpty().filter { it.isDirectory }.mapNotNull { dir ->
            val bytes = DownloadedContentManager.sizeOf(dir)
            if (bytes == 0L) return@mapNotNull null // packDir() creates empty dirs on lookup
            val pack = m.catalog().firstOrNull { it.id == dir.name }
                ?: return@mapNotNull DownloadedEntry(ContentKind.VOICE, dir.name, dir.name, bytes, ContentState.RETIRED, "No longer in the voice catalogue")
            if (pack.id in active) {
                return@mapNotNull DownloadedEntry(ContentKind.VOICE, dir.name, pack.label, bytes, ContentState.PARTIAL, "Download in progress", downloading = true)
            }
            val role = if (pack.role == "stt") "Speech recognition" else "Speech synthesis"
            val inUse = pack.id == m.selectedSttPackId() || pack.id == m.selectedTtsPackId()
            when (val verify = m.verifyInstalled(pack)) {
                "" -> DownloadedEntry(ContentKind.VOICE, dir.name, pack.label, bytes, ContentState.CURRENT, "$role · ${if (inUse) "in use · " else ""}verified")
                null -> DownloadedEntry(ContentKind.VOICE, dir.name, pack.label, bytes, ContentState.PARTIAL,
                    "$role · some files are missing — Update downloads them", updateBytes = pack.sizeBytes.coerceAtLeast(1L))
                else -> DownloadedEntry(ContentKind.VOICE, dir.name, pack.label, bytes, ContentState.UPDATE_AVAILABLE,
                    "$role · the catalogue pins a different build ($verify)", updateBytes = pack.sizeBytes.coerceAtLeast(1L))
            }
        }
    }

    override suspend fun update(entry: DownloadedEntry) {
        try {
            m.downloadPack(entry.name)
        } finally {
            // A failed artifact leaves this pack's role in DOWNLOADING; re-read disk. refreshStatus skips any
            // pack still downloading elsewhere, so it cannot wipe another download's state.
            withContext(kotlinx.coroutines.NonCancellable) { m.refreshStatus() }
        }
    }

    override suspend fun delete(entry: DownloadedEntry) = m.deleteInstalledDir(entry.name)
}

/** Kiwix ZIMs and MapLibre regions owned by [OffGridContentManager]. */
class OffGridSource(private val m: OffGridContentManager) : DownloadedContentSource {
    override val kinds = setOf(ContentKind.MAP, ContentKind.KNOWLEDGE)

    override fun busyReason(entry: DownloadedEntry): String? {
        val id = m.catalog.firstOrNull { it.id == entry.name }?.id ?: supersededBy(entry.name)?.id ?: return null
        return if (m.stateOf(id).status == OffGridStatus.DOWNLOADING) "${entry.title} is downloading; wait for it to finish" else null
    }

    override suspend fun entries(): List<DownloadedEntry> = withContext(Dispatchers.IO) {
        m.refresh()
        val out = ArrayList<DownloadedEntry>()
        for (item in m.catalog) {
            val s = m.stateOf(item.id)
            val kind = if (item.isMap) ContentKind.MAP else ContentKind.KNOWLEDGE
            val file = m.file(item)
            when {
                s.status == OffGridStatus.DOWNLOADING -> out += DownloadedEntry(kind, item.id, item.title, s.partialBytes,
                    ContentState.PARTIAL, "Download in progress (${s.progress}%)", downloading = true)
                s.status == OffGridStatus.READY -> out += DownloadedEntry(kind, item.id, item.title, s.diskBytes, ContentState.CURRENT,
                    if (item.isMap) "Offline map region" else "Verified · ${item.version}")
                !item.isMap && s.status == OffGridStatus.ERROR && file.isFile -> out += DownloadedEntry(kind, item.id, item.title,
                    file.length(), ContentState.FAILED_VERIFICATION, "Does not match the pinned checksum — Update downloads a fresh copy",
                    updateBytes = item.sizeBytes)
                s.status != OffGridStatus.DOWNLOADING && s.partialBytes > 0 -> out += DownloadedEntry(kind, item.id, item.title,
                    s.partialBytes, ContentState.PARTIAL, "Paused at ${s.progress}% — Update resumes it",
                    updateBytes = (item.sizeBytes - s.partialBytes).coerceAtLeast(1L))
            }
        }
        val catalogueNames = m.catalog.filter { !it.isMap }.flatMap { listOf(it.fileName, "${it.fileName}.partial") }.toSet()
        m.storageDir().listFiles().orEmpty().filter { it.isFile && it.name !in catalogueNames }.forEach { f ->
            val newer = supersededBy(f.name)
            out += when {
                newer == null -> DownloadedEntry(ContentKind.KNOWLEDGE, f.name, f.name, f.length(), ContentState.RETIRED,
                    "No longer in the off-grid catalogue")
                m.stateOf(newer.id).status == OffGridStatus.READY -> DownloadedEntry(ContentKind.KNOWLEDGE, f.name, newer.title, f.length(),
                    ContentState.RETIRED, "Older version ${versionOf(f.name)}; ${newer.version} is installed")
                else -> DownloadedEntry(ContentKind.KNOWLEDGE, f.name, newer.title, f.length(), ContentState.UPDATE_AVAILABLE,
                    "Version ${versionOf(f.name)} installed; ${newer.version} in the catalogue", updateBytes = newer.sizeBytes)
            }
        }
        out
    }

    /** The catalogue ZIM that replaces an older dated file of the same book, if any. */
    fun supersededBy(fileName: String): OffGridItem? {
        if (!fileName.endsWith(".zim")) return null
        val book = ZIM_DATE.replace(fileName, "")
        return m.catalog.firstOrNull { !it.isMap && ZIM_DATE.replace(it.fileName, "") == book && it.fileName > fileName }
    }

    override suspend fun update(entry: DownloadedEntry) {
        val target = m.catalog.firstOrNull { it.id == entry.name } ?: supersededBy(entry.name)
            ?: error("${entry.title} has no update in the catalogue")
        m.download(target.id)
        val after = m.stateOf(target.id)
        if (after.status != OffGridStatus.READY) error(after.error ?: "${target.title} did not finish downloading")
        // The old version is removed only once the new one verified.
        if (target.id != entry.name) m.deleteStrayFile(entry.name)
    }

    override suspend fun delete(entry: DownloadedEntry) {
        if (m.catalog.any { it.id == entry.name }) m.delete(entry.name) else m.deleteStrayFile(entry.name)
    }

    private fun versionOf(fileName: String) = ZIM_DATE.find(fileName)?.groupValues?.get(1) ?: "unknown"

    companion object {
        private val ZIM_DATE = Regex("_(\\d{4}-\\d{2})\\.zim$")
    }
}
