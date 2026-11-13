package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collect
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ModelDownloadFeedbackTest {
    private val server = MockWebServer()
    private lateinit var manager: CompanionPackManager
    private val bytes = ByteArray(64 * 1024) { (it % 251).toByte() }
    private val id = CompanionPackCatalog.ABLITERATED_17B_ID

    @Before fun setup() {
        server.start()
        val context = ApplicationProvider.getApplicationContext<Context>()
        context.getSharedPreferences("companion_pack", Context.MODE_PRIVATE).edit().clear().commit()
        context.getSharedPreferences("companion_pack_digest", Context.MODE_PRIVATE).edit().clear().commit()
        File(context.filesDir, "model-packs").deleteRecursively()
        manager = CompanionPackManager(context)
        org.robolectric.shadows.ShadowStatFs.registerStats(manager.packRoot(), 1_000_000, 1_000_000, 1_000_000)
        pin()
    }
    private fun pin(hash: String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }) {
        manager.updateCatalog(JSONObject().put("packs", JSONArray().put(JSONObject()
            .put("id", id).put("label", "Test phone model").put("filename", "feedback.gguf")
            .put("size_bytes", bytes.size).put("min_ram_mb", 1).put("sha256", hash)
            .put("url", server.url("/model").toString()))))
        manager.selectPack(id)
    }
    @After fun cleanup() { server.shutdown() }

    @Test fun connectingIsVisibleBeforeHeadersAndCancellationUnblocksNetwork() = runBlocking {
        server.enqueue(MockResponse().setHeadersDelay(2, TimeUnit.SECONDS).setBody(Buffer().write(bytes)))
        val job = launch(Dispatchers.Default) { manager.downloadSelected() }
        assertNotNull(server.takeRequest(5, TimeUnit.SECONDS))
        assertEquals(ModelDownloadStage.CONNECTING, manager.downloads.value[id]?.stage)
        assertTrue(manager.downloads.value[id]?.active == true)
        manager.cancelDownload(id)
        withTimeout(1_500) { job.join() }
        assertEquals(ModelDownloadStage.PAUSED, manager.downloads.value[id]?.stage)
        assertTrue(manager.downloadingPackIds().isEmpty())
    }

    @Test fun partialDownloadCanResumeAndOnlyBecomesReadyAfterVerification() = runBlocking {
        server.enqueue(MockResponse().setBody(Buffer().write(bytes)).throttleBody(1024, 25, TimeUnit.MILLISECONDS))
        val observed = java.util.concurrent.CopyOnWriteArrayList<ModelDownloadStage>()
        val watch = launch(Dispatchers.Unconfined) { manager.downloads.collect { it[id]?.stage?.let(observed::add) } }
        val job = launch(Dispatchers.Default) { manager.downloadSelected() }
        withTimeout(5_000) { while ((manager.downloads.value[id]?.receivedBytes ?: 0) == 0L) delay(10) }
        assertTrue(runCatching { manager.downloadSelected() }.isFailure)
        manager.cancelDownload(id)
        withTimeout(2_000) { job.join() }
        val partial = File(manager.packRoot(), "feedback.gguf.partial")
        val offset = partial.length().toInt()
        assertTrue(offset in 1 until bytes.size)
        assertFalse(manager.packFile(manager.selectedPack()!!).exists())
        server.takeRequest(5, TimeUnit.SECONDS)
        server.enqueue(MockResponse().setResponseCode(206).setBody(Buffer().write(bytes, offset, bytes.size - offset)))
        manager.downloadSelected()
        assertEquals("bytes=$offset-", server.takeRequest(5, TimeUnit.SECONDS)?.getHeader("Range"))
        assertEquals(ModelDownloadStage.READY, manager.downloads.value[id]?.stage)
        assertTrue(observed.contains(ModelDownloadStage.VERIFYING))
        assertArrayEquals(bytes, manager.packFile(manager.selectedPack()!!).readBytes())
        assertFalse(partial.exists())
        watch.cancelAndJoin()
    }

    @Test fun checksumFailureIsAnInlineErrorAndNeverReady() = runBlocking {
        pin("0".repeat(64))
        server.enqueue(MockResponse().setBody(Buffer().write(bytes)))
        assertTrue(runCatching { manager.downloadSelected() }.isFailure)
        val state = manager.downloads.value.getValue(id)
        assertEquals(ModelDownloadStage.ERROR, state.stage)
        assertFalse(state.active)
        assertTrue(state.detail.contains("checksum"))
        assertFalse(manager.packFile(manager.selectedPack()!!).exists())
    }

    @Test fun transientServerFailureShowsRetryAndRecovers() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(503))
        server.enqueue(MockResponse().setBody(Buffer().write(bytes)))
        val observed = java.util.concurrent.CopyOnWriteArrayList<ModelDownloadStage>()
        val watch = launch(Dispatchers.Unconfined) { manager.downloads.collect { it[id]?.stage?.let(observed::add) } }
        try {
            withTimeout(10_000) { manager.downloadSelected() }
            assertTrue(observed.contains(ModelDownloadStage.RETRYING))
            assertEquals(ModelDownloadStage.READY, manager.downloads.value[id]?.stage)
        } finally { watch.cancelAndJoin() }
    }
}
