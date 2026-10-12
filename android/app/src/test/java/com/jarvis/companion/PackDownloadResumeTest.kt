package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.sun.net.httpserver.HttpServer
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowStatFs
import java.net.InetSocketAddress
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList

/** Auto-retry + Range resume of a dropped pack download against a real local HTTP server. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class PackDownloadResumeTest {
    private lateinit var server: HttpServer
    private val payload = ByteArray(300_000) { (it % 251).toByte() }
    private val ranges = CopyOnWriteArrayList<String>()

    @Before
    fun startServer() {
        var first = true
        server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/pack.gguf") { exchange ->
            val range = exchange.requestHeaders.getFirst("Range")
            ranges += range ?: "none"
            if (first) {
                // Promise the whole file, send half, then drop the connection.
                first = false
                exchange.sendResponseHeaders(200, payload.size.toLong())
                exchange.responseBody.write(payload, 0, payload.size / 2)
                exchange.responseBody.flush()
                exchange.close()
                return@createContext
            }
            val from = range!!.removePrefix("bytes=").removeSuffix("-").toInt()
            exchange.responseHeaders.add("Content-Range", "bytes $from-${payload.size - 1}/${payload.size}")
            exchange.sendResponseHeaders(206, (payload.size - from).toLong())
            exchange.responseBody.write(payload, from, payload.size - from)
            exchange.close()
        }
        server.start()
    }

    @After
    fun stopServer() = server.stop(0)

    @Test
    fun droppedDownloadRetriesAndResumesWithRange() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        ShadowStatFs.registerStats(context.filesDir.absolutePath + "/model-packs", 1_000_000, 1_000_000, 1_000_000)
        val sha = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        val pack = JSONObject()
            .put("id", "resume-test")
            .put("label", "Resume test")
            .put("filename", "resume-test.gguf")
            .put("size_bytes", payload.size.toLong())
            .put("min_ram_mb", 1)
            .put("sha256", sha)
            .put("url", "http://127.0.0.1:${server.address.port}/pack.gguf")
        val manager = CompanionPackManager(context, ScriptedInferenceEngine("unused"))
        manager.updateCatalog(JSONObject().put("packs", JSONArray().put(pack)))
        manager.selectPack("resume-test")

        manager.downloadSelected()

        assertEquals(listOf("none", "bytes=${payload.size / 2}-"), ranges.toList())
        val file = manager.packFile(manager.selectedPack()!!)
        assertArrayEquals(payload, file.readBytes())
        assertEquals(CompanionPackStatus.READY, manager.status())
        assertTrue(manager.lastError().isEmpty())
    }
}
