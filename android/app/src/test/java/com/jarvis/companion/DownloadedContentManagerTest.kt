package com.jarvis.companion

import android.content.Context
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.security.MessageDigest

private fun sha256(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

/** RFC-0216 S5 aggregator over the real pack managers (app-private storage under Robolectric). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class DownloadedContentManagerTest {
    @get:Rule val tmp = TemporaryFolder()
    private val server = MockWebServer()
    private lateinit var context: Context
    private lateinit var models: CompanionPackManager
    private lateinit var voice: CompanionVoicePackManager

    private val modelBytes = ByteArray(4096) { (it % 251).toByte() }
    private val zimBytes = ByteArray(3000) { (it % 13).toByte() }

    private class NoMaps : OffGridMapStore {
        override suspend fun states(items: List<OffGridItem>) = items.associate { it.id to OffGridItemState() }
        override suspend fun download(item: OffGridItem, onState: (OffGridItemState) -> Unit) = error("no maps in this test")
        override suspend fun pause(item: OffGridItem) {}
        override suspend fun delete(item: OffGridItem) {}
    }

    @Before fun setUp() {
        server.start()
        context = ApplicationProvider.getApplicationContext()
        listOf("companion_pack", "companion_pack_digest", "companion_voice_pack", "companion_voice_digest").forEach {
            context.getSharedPreferences(it, Context.MODE_PRIVATE).edit().clear().commit()
        }
        File(context.filesDir, "model-packs").deleteRecursively()
        File(context.filesDir, "voice-packs").deleteRecursively()
        models = CompanionPackManager(context)
        voice = CompanionVoicePackManager(context)
        pinModel(sha256(modelBytes))
        models.selectPack(CompanionPackCatalog.INSTRUCT_15B_ID)
    }

    @After fun tearDown() = server.shutdown()

    private fun pinModel(sha: String) = models.updateCatalog(JSONObject().put("packs", JSONArray().put(JSONObject()
        .put("id", CompanionPackCatalog.INSTRUCT_15B_ID).put("filename", "tiny.gguf").put("size_bytes", modelBytes.size.toLong())
        .put("sha256", sha).put("url", server.url("/tiny.gguf").toString()))))

    private fun zimItem() = OffGridItem("zim-water", "Water", OffGridCategory.SURVIVAL, zimBytes.size.toLong(), sha256(zimBytes),
        server.url("/zim/water_en_2026-08.zim").toString(), version = "2026-08")

    private fun offGrid(root: File = tmp.newFolder()) = OffGridContentManager(root, VerifiedDigestCache(), NoMaps(), listOf(zimItem()),
        freeBytes = { Long.MAX_VALUE }, retrySleep = {}, urlScheme = "http://")

    private fun installModel(bytes: ByteArray = modelBytes) = File(models.packRoot(), "tiny.gguf").apply { writeBytes(bytes) }

    @Test fun inventory_lists_every_kind_with_on_disk_sizes_and_total() = runBlocking {
        installModel()
        File(models.packRoot(), "old-model.gguf").writeBytes(ByteArray(100))
        val stt = voice.selectedSttPack()!!
        voice.artifactFile(stt, stt.artifacts.first()).apply { parentFile!!.mkdirs(); writeBytes(ByteArray(700)) }
        File(voice.packRoot(), "retired-voice").apply { mkdirs(); File(this, "a.bin").writeBytes(ByteArray(50)) }
        val og = offGrid()
        File(og.storageDir(), "water_en_2026-08.zim").writeBytes(zimBytes)
        File(og.storageDir(), "water_en_2025-01.zim").writeBytes(ByteArray(1234))
        File(og.storageDir(), "unknown_2020-01.zim").writeBytes(ByteArray(10))

        val inv = DownloadedContentManager.forManagers(models, voice, og).inventory()
        val byName = inv.entries.associateBy { it.name }
        assertEquals(inv.errors.toString(), emptyList<String>(), inv.errors)
        assertEquals(ContentState.CURRENT, byName.getValue("tiny.gguf").state)
        assertEquals(modelBytes.size.toLong(), byName.getValue("tiny.gguf").bytes)
        assertEquals(ContentState.RETIRED, byName.getValue("old-model.gguf").state)
        val sttRow = byName.getValue(stt.id)
        assertEquals(ContentKind.VOICE, sttRow.kind)
        assertEquals(700L, sttRow.bytes)
        assertTrue("corrupt artifact must be offered for update: ${sttRow.state}", sttRow.canUpdate)
        assertEquals(ContentState.RETIRED, byName.getValue("retired-voice").state)
        assertEquals(ContentState.CURRENT, byName.getValue("zim-water").state)
        assertEquals(zimBytes.size.toLong(), byName.getValue("zim-water").bytes)
        // Older dated file of a book whose newer version is installed is delete-only.
        assertEquals(ContentState.RETIRED, byName.getValue("water_en_2025-01.zim").state)
        assertEquals(ContentState.RETIRED, byName.getValue("unknown_2020-01.zim").state)
        val onDisk = modelBytes.size + 100L + 700 + 50 + zimBytes.size + 1234 + 10
        assertEquals(onDisk, inv.totalBytes)
        assertEquals(700L + 50, inv.bytesOf(ContentKind.VOICE))
    }

    @Test fun delete_model_frees_file_and_offline_chat_fails_closed() = runBlocking {
        val file = installModel()
        models.refreshStatus()
        assertNotNull(models.resolveOfflinePack())
        val mgr = DownloadedContentManager.forManagers(models, voice, null)
        mgr.delete(mgr.inventory().entries.single { it.name == "tiny.gguf" })
        assertFalse(file.exists())
        assertNull(models.resolveOfflinePack())
        assertFalse(models.isPackReady())
        assertEquals(CompanionPackStatus.MISSING, models.status())
        assertTrue(mgr.inventory().entries.none { it.kind == ContentKind.MODEL })
    }

    @Test fun delete_voice_pack_marks_missing_and_not_installed() = runBlocking {
        val stt = voice.selectedSttPack()!!
        voice.artifactFile(stt, stt.artifacts.first()).apply { parentFile!!.mkdirs(); writeBytes(ByteArray(10)) }
        val mgr = DownloadedContentManager.forManagers(models, voice, null)
        mgr.delete(mgr.inventory().entries.single { it.name == stt.id })
        assertFalse(voice.isPackInstalled(stt.id))
        assertEquals(CompanionVoicePackStatus.MISSING, voice.sttStatus())
        assertEquals(0L, DownloadedContentManager.sizeOf(File(voice.packRoot(), stt.id)))
        assertTrue(mgr.inventory().entries.none { it.kind == ContentKind.VOICE })
    }

    @Test fun model_update_failure_keeps_last_copy_and_success_reverifies() = runBlocking {
        // Robolectric reports 0 free bytes unless the volume is registered.
        org.robolectric.shadows.ShadowStatFs.registerStats(models.packRoot(), 1_000_000, 1_000_000, 1_000_000)
        val old = ByteArray(modelBytes.size) { 7 }
        installModel(old)
        val mgr = DownloadedContentManager.forManagers(models, voice, null)
        val row = mgr.inventory().entries.single { it.name == "tiny.gguf" }
        assertEquals(ContentState.UPDATE_AVAILABLE, row.state)

        server.enqueue(MockResponse().setBody(Buffer().write(ByteArray(modelBytes.size) { 9 }))) // wrong bytes
        val failure = runCatching { mgr.update(row) }.exceptionOrNull()
        assertNotNull(failure)
        assertArrayEquals("failed update must not touch the installed file", old, File(models.packRoot(), "tiny.gguf").readBytes())
        assertFalse(File(models.packRoot(), "tiny.gguf.partial").exists())

        server.enqueue(MockResponse().setBody(Buffer().write(modelBytes)))
        mgr.update(row)
        assertArrayEquals(modelBytes, File(models.packRoot(), "tiny.gguf").readBytes())
        assertEquals(ContentState.CURRENT, mgr.inventory().entries.single { it.name == "tiny.gguf" }.state)
        assertEquals(CompanionPackStatus.READY, models.status())
    }

    @Test fun zim_newer_version_update_replaces_old_only_after_verify() = runBlocking {
        val og = offGrid()
        val oldFile = File(og.storageDir(), "water_en_2025-01.zim").apply { writeBytes(ByteArray(500) { 1 }) }
        val mgr = DownloadedContentManager.forManagers(models, voice, og)
        val row = mgr.inventory().entries.single { it.name == oldFile.name }
        assertEquals(ContentState.UPDATE_AVAILABLE, row.state)
        assertEquals(zimBytes.size.toLong(), row.updateBytes)

        server.enqueue(MockResponse().setBody(Buffer().write(ByteArray(zimBytes.size) { 2 })))
        assertNotNull(runCatching { mgr.update(row) }.exceptionOrNull())
        assertTrue("old version kept when the new one fails verification", oldFile.exists())

        server.enqueue(MockResponse().setBody(Buffer().write(zimBytes)))
        mgr.update(row)
        assertFalse(oldFile.exists())
        assertEquals(OffGridStatus.READY, og.stateOf("zim-water").status)
        val after = mgr.inventory().entries.filter { it.kind == ContentKind.KNOWLEDGE }
        assertEquals(listOf("zim-water"), after.map { it.name })
        // Deleting the catalogue ZIM makes the reader fail closed.
        mgr.delete(after.single())
        assertNotNull(runCatching { og.verifiedZim("zim-water") }.exceptionOrNull())
    }

    @Test fun running_download_locks_rows_and_refreshes_cannot_wipe_its_state() = runBlocking {
        org.robolectric.shadows.ShadowStatFs.registerStats(models.packRoot(), 1_000_000, 1_000_000, 1_000_000)
        models.updateCatalog(JSONObject().put("packs", JSONArray()
            .put(JSONObject().put("id", CompanionPackCatalog.INSTRUCT_15B_ID).put("filename", "tiny.gguf")
                .put("size_bytes", modelBytes.size.toLong()).put("sha256", sha256(modelBytes)).put("url", server.url("/tiny.gguf").toString()))
            .put(JSONObject().put("id", CompanionPackCatalog.INSTRUCT_3B_ID).put("filename", "other.gguf")
                .put("size_bytes", 10L).put("sha256", "00").put("url", server.url("/missing.gguf").toString()))))
        server.dispatcher = object : okhttp3.mockwebserver.Dispatcher() {
            override fun dispatch(request: okhttp3.mockwebserver.RecordedRequest): MockResponse =
                if (request.path == "/tiny.gguf") MockResponse().setBody(Buffer().write(modelBytes))
                    .throttleBody(512, 250, java.util.concurrent.TimeUnit.MILLISECONDS) // ~2 s
                else MockResponse().setResponseCode(404)
        }
        File(models.packRoot(), "old-model.gguf").writeBytes(ByteArray(100))
        val download = kotlinx.coroutines.GlobalScope.async(kotlinx.coroutines.Dispatchers.IO) { models.downloadSelected() }
        val partial = File(models.packRoot(), "tiny.gguf.partial")
        val deadline = System.currentTimeMillis() + 5_000
        while (!(partial.length() > 0 && models.downloadingPackIds().isNotEmpty()) && System.currentTimeMillis() < deadline) Thread.sleep(20)
        assertTrue("download should be running", partial.length() > 0)

        val mgr = DownloadedContentManager.forManagers(models, voice, null)
        val rows = mgr.inventory().entries.associateBy { it.name }
        assertTrue(rows.getValue("tiny.gguf.partial").downloading)
        assertTrue("other model rows are locked too", rows.getValue("old-model.gguf").downloading)
        assertFalse(rows.getValue("tiny.gguf.partial").canUpdate)
        assertNotNull(runCatching { mgr.delete(rows.getValue("old-model.gguf")) }.exceptionOrNull())
        assertNotNull(runCatching { mgr.update(rows.getValue("tiny.gguf.partial").copy(updateBytes = 1)) }.exceptionOrNull())
        assertNotNull(runCatching { models.deleteInstalledFile("old-model.gguf") }.exceptionOrNull())
        assertTrue(File(models.packRoot(), "old-model.gguf").exists())

        // Neither an explicit refresh nor a second (failing) pack download's cleanup may wipe DOWNLOADING.
        models.refreshStatus()
        assertEquals(CompanionPackStatus.DOWNLOADING, models.status())
        val other = models.catalog().first { it.id == CompanionPackCatalog.INSTRUCT_3B_ID }
        assertNotNull(runCatching { models.downloadPack(other) }.exceptionOrNull())
        assertTrue(download.isActive)
        assertEquals(CompanionPackStatus.DOWNLOADING, models.status())
        assertNotNull("same pack cannot start twice", runCatching { models.downloadSelected() }.exceptionOrNull())

        download.await()
        assertEquals(CompanionPackStatus.READY, models.status())
        val after = mgr.inventory().entries.associateBy { it.name }
        assertEquals(ContentState.CURRENT, after.getValue("tiny.gguf").state)
        assertFalse(after.getValue("old-model.gguf").downloading)
        mgr.delete(after.getValue("old-model.gguf"))
        assertFalse(File(models.packRoot(), "old-model.gguf").exists())
    }

    @Test fun page_works_without_offgrid_and_reports_a_broken_source() = runBlocking {
        installModel()
        val inv = DownloadedContentManager.forManagers(models, voice, null).inventory()
        assertTrue(inv.entries.none { it.kind == ContentKind.MAP || it.kind == ContentKind.KNOWLEDGE })
        val broken = object : DownloadedContentSource {
            override val kinds = setOf(ContentKind.MAP)
            override suspend fun entries(): List<DownloadedEntry> = error("offline DB unreadable")
            override suspend fun update(entry: DownloadedEntry) {}
            override suspend fun delete(entry: DownloadedEntry) {}
        }
        val mixed = DownloadedContentManager(listOf(ModelPackSource(models), broken)).inventory()
        assertEquals(1, mixed.entries.size)
        assertTrue(mixed.errors.single().contains("offline DB unreadable"))
    }

    @Test fun paths_outside_storage_are_refused() = runBlocking {
        assertNotNull(runCatching { models.deleteInstalledFile("../shared_prefs/x.xml") }.exceptionOrNull())
        assertNotNull(runCatching { voice.deleteInstalledDir("..") }.exceptionOrNull())
        assertNotNull(runCatching { voice.deleteInstalledDir(".") }.exceptionOrNull())
        assertTrue(voice.packRoot().exists())
        assertNotNull(runCatching { offGrid().deleteStrayFile("water_en_2026-08.zim") }.exceptionOrNull())
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w411dp-h2000dp")
class DownloadedContentPageTest {
    @get:Rule val compose = createComposeRule()

    private val current = DownloadedEntry(ContentKind.MODEL, "a.gguf", "Qwen tiny", 2_000_000_000L, ContentState.CURRENT, "Verified")
    private val stale = DownloadedEntry(ContentKind.KNOWLEDGE, "w_2025-01.zim", "Water", 50_000_000L, ContentState.UPDATE_AVAILABLE,
        "newer in catalogue", updateBytes = 60_000_000L)

    private fun show(deleted: MutableList<String>, updated: MutableList<String>) = compose.setContent {
        DownloadedContentPage(DownloadedInventory(listOf(current, stale), emptyList()), null, null,
            onUpdate = { updated += it.name }, onDelete = { deleted += it.name }, onClose = {})
    }

    @Test fun shows_sizes_total_and_update_only_where_available() {
        show(mutableListOf(), mutableListOf())
        compose.onNodeWithText("Total: 2.1 GB").assertExists()
        compose.onNodeWithText("Qwen tiny · 2.0 GB").assertExists()
        compose.onNodeWithText("Phone AI models · 2.0 GB").assertExists()
        compose.onAllNodesWithText("Update").assertCountEquals(1)
        compose.onAllNodesWithText("Delete").assertCountEquals(2)
        compose.onAllNodesWithText("Nothing downloaded").assertCountEquals(2) // voice + maps
    }

    @Test fun delete_needs_confirmation_and_cancel_does_nothing() {
        val deleted = mutableListOf<String>(); val updated = mutableListOf<String>()
        show(deleted, updated)
        compose.onAllNodesWithText("Delete")[0].performClick()
        compose.onNodeWithText("Delete Qwen tiny?").assertExists()
        compose.onNodeWithText("Frees 2.0 GB", substring = true).assertExists()
        compose.onNodeWithText("Cancel").performClick()
        assertTrue(deleted.isEmpty())
        compose.onAllNodesWithText("Delete")[0].performClick()
        compose.onNode(hasText("Delete") and hasAnyAncestor(isDialog())).performClick()
        assertEquals(listOf("a.gguf"), deleted)
        assertTrue(updated.isEmpty())
    }

    @Test fun downloading_row_shows_progress_and_disables_both_actions() {
        val busy = stale.copy(downloading = true, detail = "Download in progress")
        compose.setContent {
            DownloadedContentPage(DownloadedInventory(listOf(busy), emptyList()), null, null, onUpdate = {}, onDelete = {}, onClose = {})
        }
        compose.onNodeWithText("Downloading…").assertExists()
        compose.onNodeWithText("Update").assertIsNotEnabled()
        compose.onNodeWithText("Delete").assertIsNotEnabled()
    }

    @Test fun update_needs_confirmation() {
        val deleted = mutableListOf<String>(); val updated = mutableListOf<String>()
        show(deleted, updated)
        compose.onNode(hasText("Update") and !hasAnyAncestor(isDialog())).performClick()
        compose.onNodeWithText("Update Water?").assertExists()
        compose.onNodeWithText("The current copy stays", substring = true).assertExists()
        compose.onNode(hasText("Update") and hasAnyAncestor(isDialog())).performClick()
        assertEquals(listOf("w_2025-01.zim"), updated)
        assertTrue(deleted.isEmpty())
    }
}
