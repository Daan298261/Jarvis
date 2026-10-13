package com.jarvis.companion

import android.annotation.SuppressLint
import android.content.Context
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import java.io.ByteArrayInputStream
import java.io.File
import org.kiwix.libkiwix.JNIKiwix
import org.kiwix.libzim.Archive
import org.kiwix.libzim.Query
import org.kiwix.libzim.Searcher
import org.kiwix.libzim.SuggestionSearcher

/** Loads libkiwix/libzim once. Returns null when ready, or actionable copy when the native libs are missing. */
object ZimNative {
    @Volatile private var loaded = false
    @Volatile private var failure: String? = null

    @Synchronized
    fun ensureLoaded(context: Context): String? {
        if (loaded) return null
        failure?.let { return it }
        return try {
            JNIKiwix(context.applicationContext)
            loaded = true
            null
        } catch (e: Throwable) { // UnsatisfiedLinkError, MissingLibraryException from ReLinker
            "The offline knowledge reader (libkiwix) could not load on this phone: ${e.message ?: e.javaClass.simpleName}. Reinstall ANZU or report this build."
                .also { failure = it }
        }
    }
}

data class ZimHit(val title: String, val path: String, val snippet: String = "")

/** URL scheme the reader WebView uses; only this host is ever served, everything else is blocked offline. */
object ZimUrls {
    const val HOST = "zim.anzu.local"
    const val BASE = "https://$HOST/"
    fun forPath(path: String): String = BASE + path.split('/').joinToString("/") { android.net.Uri.encode(it) }
    fun pathOf(url: String): String? =
        if (url.startsWith(BASE)) android.net.Uri.decode(url.removePrefix(BASE).substringBefore('#').substringBefore('?')) else null
}

/** Something the reader WebView can pull archive entries from. */
fun interface ZimSource { fun load(path: String): Pair<ByteArray, String>? }

/**
 * Serialises reads against [close]: once closed, reads return null and never touch the native archive,
 * so a WebView request racing dialog dismissal cannot use a disposed handle.
 */
class GuardedZimSource(private val read: (String) -> Pair<ByteArray, String>?, private val dispose: () -> Unit) : ZimSource, AutoCloseable {
    private val lock = Any()
    @Volatile var closed = false
        private set
    override fun load(path: String): Pair<ByteArray, String>? = synchronized(lock) { if (closed) null else read(path) }
    override fun close() = synchronized(lock) { if (!closed) { closed = true; dispose() } }
}

/** A verified, opened ZIM archive. Use from a background thread; [close] when done. */
class ZimBook(file: File) : ZimSource, AutoCloseable {
    private val archive = Archive(file.absolutePath)
    private val guard = GuardedZimSource(::loadUnguarded) { archive.dispose() }

    val mainPath: String? get() = if (archive.hasMainEntry()) archive.mainEntry.getItem(true).path else null

    fun search(text: String, limit: Int = 30): List<ZimHit> {
        if (text.isBlank() || guard.closed) return emptyList()
        val hits = LinkedHashMap<String, ZimHit>()
        if (archive.hasTitleIndex()) {
            val it = SuggestionSearcher(archive).suggest(text).getResults(0, limit)
            while (it.hasNext()) { val s = it.next(); hits.putIfAbsent(s.path, ZimHit(s.title, s.path, if (s.hasSnippet()) s.snippet else "")) }
        }
        if (archive.hasFulltextIndex() && hits.size < limit) {
            val it = Searcher(archive).search(Query(text)).getResults(0, limit - hits.size)
            while (it.hasNext()) {
                val entry = it.next()
                hits.putIfAbsent(entry.path, ZimHit(entry.title, entry.path))
            }
        }
        return hits.values.toList()
    }

    /** Bytes + mime for a path, following redirects; null when absent or closed. */
    override fun load(path: String): Pair<ByteArray, String>? = guard.load(path)

    private fun loadUnguarded(path: String): Pair<ByteArray, String>? {
        if (!archive.hasEntryByPath(path)) return null
        val item = archive.getEntryByPath(path).getItem(true)
        return item.data.data to item.mimetype
    }

    override fun close() = guard.close()
}

/** Serves ZIM entries to the WebView and blocks every other request, so reading never touches the network. */
class ZimWebViewClient(private val book: ZimSource, private val onError: (String) -> Unit) : WebViewClient() {
    override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse {
        val path = ZimUrls.pathOf(request.url.toString())
            ?: return WebResourceResponse("text/plain", "utf-8", 403, "Offline", emptyMap(), ByteArrayInputStream(ByteArray(0)))
        val loaded = runCatching { book.load(path) }.getOrNull()
            ?: return WebResourceResponse("text/plain", "utf-8", 404, "Not in archive", emptyMap(), ByteArrayInputStream(ByteArray(0)))
        val mime = loaded.second.substringBefore(';').trim()
        return WebResourceResponse(mime, if (mime.startsWith("text/")) "utf-8" else null, ByteArrayInputStream(loaded.first))
    }

    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
        if (ZimUrls.pathOf(request.url.toString()) != null) return false
        onError("External links are not available off-grid.")
        return true
    }

    companion object {
        @SuppressLint("SetJavaScriptEnabled")
        fun configure(web: WebView) {
            web.settings.javaScriptEnabled = true
            web.settings.allowFileAccess = false
            web.settings.allowContentAccess = false
            web.settings.blockNetworkLoads = false // requests are intercepted; non-ZIM hosts get 403
        }
    }
}
