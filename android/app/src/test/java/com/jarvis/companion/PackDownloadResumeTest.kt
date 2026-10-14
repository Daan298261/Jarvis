package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
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
import java.net.InetAddress
import java.net.ServerSocket
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

/** Auto-retry + Range resume of a dropped pack download against a real local HTTP server. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class PackDownloadResumeTest {
    private lateinit var server: ServerSocket
    private val payload = ByteArray(300_000) { (it % 251).toByte() }
    private val ranges = CopyOnWriteArrayList<String>()

    /** Tiny HTTP/1.1 server: first request drops mid-body, later ones honour Range with 206. */
    @Before
    fun startServer() {
        server = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
        thread(isDaemon = true) {
            var first = true
            while (!server.isClosed) {
                val socket = runCatching { server.accept() }.getOrNull() ?: break
                socket.use { client ->
                    val reader = client.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                    var range: String? = null
                    while (true) {
                        val line = reader.readLine() ?: break
                        if (line.isEmpty()) break
                        if (line.startsWith("Range:", ignoreCase = true)) range = line.substringAfter(":").trim()
                    }
                    ranges += range ?: "none"
                    val out = client.getOutputStream()
                    if (first) {
                        first = false
                        out.write("HTTP/1.1 200 OK\r\nContent-Length: ${payload.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        out.write(payload, 0, payload.size / 2)
                        out.flush()
                    } else {
                        val from = range!!.removePrefix("bytes=").removeSuffix("-").toInt()
                        out.write(
                            ("HTTP/1.1 206 Partial Content\r\nContent-Length: ${payload.size - from}\r\n" +
                                "Content-Range: bytes $from-${payload.size - 1}/${payload.size}\r\nConnection: close\r\n\r\n").toByteArray(),
                        )
                        out.write(payload, from, payload.size - from)
                        out.flush()
                    }
                }
            }
        }
    }

    @After
    fun stopServer() = server.close()

    @Test
    fun droppedDownloadRetriesAndResumesWithRange() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        ShadowStatFs.registerStats(java.io.File(context.filesDir, "model-packs"), 1_000_000, 1_000_000, 1_000_000)
        val sha = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        val pack = JSONObject()
            .put("id", "resume-test")
            .put("label", "Resume test")
            .put("filename", "resume-test.gguf")
            .put("size_bytes", payload.size.toLong())
            .put("min_ram_mb", 1)
            .put("sha256", sha)
            .put("url", "http://127.0.0.1:${server.localPort}/pack.gguf")
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
