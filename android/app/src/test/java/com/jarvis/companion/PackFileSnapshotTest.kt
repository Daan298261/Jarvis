package com.jarvis.companion

import android.content.Context
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.util.concurrent.Executors
import kotlin.coroutines.CoroutineContext

/** Pack files (installed check, `.partial` size, storage) are read on IO, never on the main thread. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PackFileSnapshotTest {
    private val ioPool = Executors.newSingleThreadExecutor { Thread(it, "pack-io-test") }

    /** Records every dispatch so the test can prove the snapshot hopped off the calling thread. */
    private class RecordingDispatcher(private val delegate: CoroutineDispatcher) : CoroutineDispatcher() {
        @Volatile var dispatches = 0
        override fun dispatch(context: CoroutineContext, block: Runnable) {
            dispatches++
            delegate.dispatch(context, Runnable { block.run() })
        }
    }

    @After fun shutdown() { ioPool.shutdownNow() }

    @Test fun snapshotReadsPackFilesOnTheFileDispatcherNotTheMainThread() = runBlocking {
        assertSame(Looper.getMainLooper().thread, Thread.currentThread())  // Robolectric test thread is main
        val context = ApplicationProvider.getApplicationContext<Context>()
        File(context.filesDir, "model-packs").deleteRecursively()
        val io = RecordingDispatcher(ioPool.asCoroutineDispatcher())
        val manager = CompanionPackManager(context, ScriptedInferenceEngine("unused"), fileDispatcher = io)
        manager.updateCatalog(JSONObject().put("packs", JSONArray()
            .put(JSONObject().put("id", "plain").put("label", "Plain").put("filename", "plain.gguf")
                .put("size_bytes", 4).put("min_ram_mb", 1).put("url", "https://example.invalid/plain"))
            .put(JSONObject().put("id", "partial").put("label", "Partial").put("filename", "partial.gguf")
                .put("size_bytes", 100).put("min_ram_mb", 1).put("url", "https://example.invalid/partial"))))
        File(manager.packRoot(), "plain.gguf").writeBytes(byteArrayOf(1, 2, 3, 4))
        File(manager.packRoot(), "partial.gguf.partial").writeBytes(ByteArray(10))

        val snapshot = manager.packFileSnapshot()

        assertTrue("snapshot must run on the file dispatcher", io.dispatches > 0)
        assertEquals(true, snapshot.installed["plain"])
        assertEquals(false, snapshot.installed["partial"])
        assertEquals(10L, snapshot.resumeBytes["partial"])
        assertEquals(14L, snapshot.storageBytes)
    }

    @Test fun chromeStateTakesFileFactsFromTheSnapshotWithoutTouchingDisk() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val manager = CompanionPackManager(context, ScriptedInferenceEngine("unused"))
        val pack = manager.catalog().first()
        // Nothing for this pack exists on disk; the published state must still mirror the snapshot.
        val files = PackFileSnapshot(installed = mapOf(pack.id to true), resumeBytes = mapOf(pack.id to 42L), storageBytes = 7L)
        val state = DevicePackChromePublisher.buildState(manager, CompanionState(), files)
        val option = state.availablePacks.first { it.id == pack.id }
        assertTrue(option.installed)
        assertEquals(42L, option.resumeBytes)
        assertEquals(7L, state.bytesOnDisk)
    }
}
