package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowStatFs
import java.io.ByteArrayInputStream
import java.io.File
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class ModelSideloadTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    private val gguf = "GGUF".toByteArray() + ByteArray(50_000) { (it % 199).toByte() }
    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun manager(sha256: String = sha(gguf), size: Long = gguf.size.toLong()): CompanionPackManager {
        File(context.filesDir, "model-packs").deleteRecursively()
        File(context.filesDir, "model-packs").mkdirs()
        ShadowStatFs.registerStats(File(context.filesDir, "model-packs"), 1_000_000, 1_000_000, 1_000_000)
        val pack = JSONObject()
            .put("id", "sideload-test")
            .put("label", "Sideload test")
            .put("filename", "sideload-test.gguf")
            .put("size_bytes", size)
            .put("min_ram_mb", 1)
            .put("sha256", sha256)
            .put("url", "https://example.invalid/sideload-test.gguf")
        return CompanionPackManager(context, ScriptedInferenceEngine("unused")).also {
            it.updateCatalog(JSONObject().put("packs", JSONArray().put(pack)))
        }
    }

    @Before
    fun reset() {
        context.getSharedPreferences("companion_pack", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test
    fun ggufHeaderDetection() {
        assertTrue(ModelSideload.isGgufHeader("GGUFxxxx".toByteArray()))
        assertFalse(ModelSideload.isGgufHeader("PK\u0003\u0004".toByteArray()))
        assertFalse(ModelSideload.isGgufHeader("GG".toByteArray()))
    }

    @Test
    fun matchRequiresPinnedHashAndSize() {
        val pack = CompanionPackCatalog.builtIn.first()
        assertEquals(pack, ModelSideload.match(pack.sha256.uppercase(), pack.sizeBytes, CompanionPackCatalog.builtIn))
        assertNull(ModelSideload.match(pack.sha256, pack.sizeBytes - 1, CompanionPackCatalog.builtIn))
        assertNull(ModelSideload.match("0".repeat(64), pack.sizeBytes, CompanionPackCatalog.builtIn))
    }

    @Test
    fun verifiedFileIsImportedSelectedAndReady() = runBlocking {
        val manager = manager()
        val progress = mutableListOf<Int>()
        val pack = manager.importSideloaded(ByteArrayInputStream(gguf), gguf.size.toLong()) { progress += it }
        assertEquals("sideload-test", pack.id)
        assertEquals("sideload-test", manager.selectedPackId())
        assertArrayEquals(gguf, manager.packFile(pack).readBytes())
        assertEquals(CompanionPackStatus.READY, manager.status())
        assertEquals(100, progress.last())
        assertTrue(manager.isPackReady())
        assertTrue(File(context.filesDir, "model-packs").listFiles()!!.none { it.name.endsWith(".importing") })
    }

    @Test
    fun unknownHashIsRejectedAndLeavesNoFile() = runBlocking {
        val manager = manager(sha256 = "ab".repeat(32))
        try {
            manager.importSideloaded(ByteArrayInputStream(gguf), gguf.size.toLong())
            fail("expected rejection")
        } catch (error: IllegalStateException) {
            assertTrue(error.message!!.contains("does not match any model"))
        }
        assertEquals(CompanionPackStatus.MISSING, manager.status())
        assertTrue(manager.lastError().contains("does not match"))
        assertTrue(File(context.filesDir, "model-packs").listFiles()!!.isEmpty())
    }

    @Test
    fun nonGgufIsRejected() = runBlocking {
        val zip = "PK".toByteArray() + ByteArray(100)
        val manager = manager(sha256 = sha(zip), size = zip.size.toLong())
        try {
            manager.importSideloaded(ByteArrayInputStream(zip), zip.size.toLong())
            fail("expected rejection")
        } catch (error: IllegalStateException) {
            assertEquals(ModelSideload.notGgufCopy(), error.message)
        }
    }

    @Test
    fun rejectedFileDoesNotBreakInstalledModel() = runBlocking {
        val manager = manager()
        manager.importSideloaded(ByteArrayInputStream(gguf), gguf.size.toLong())
        val other = "GGUF".toByteArray() + ByteArray(10) { 7 }
        runCatching { manager.importSideloaded(ByteArrayInputStream(other), other.size.toLong()) }
        assertEquals(CompanionPackStatus.READY, manager.status())
        assertTrue(manager.lastError().contains("does not match"))
    }

    @Test
    fun oversizedFileIsRejectedBeforeCopy() = runBlocking {
        val manager = manager()
        try {
            manager.importSideloaded(ByteArrayInputStream(gguf), Long.MAX_VALUE / 2)
            fail("expected rejection")
        } catch (error: IllegalStateException) {
            assertTrue(error.message!!.contains("larger than"))
        }
    }
}
