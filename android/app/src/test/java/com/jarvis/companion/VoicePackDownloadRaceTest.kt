package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Voice-pack mirror of DownloadedContentManagerTest.running_download_locks_rows_and_refreshes_cannot_wipe_its_state:
 * while one voice download runs, a VoicePackSource refresh and a second, failing download must leave the
 * running download's status and progress untouched.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class VoicePackDownloadRaceTest {
    private val server = MockWebServer()
    private lateinit var voice: CompanionVoicePackManager
    private val slowBytes = ByteArray(4096) { (it % 251).toByte() }

    private fun sha256(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

    @Before fun setUp() {
        server.start()
        val context: Context = ApplicationProvider.getApplicationContext()
        listOf("companion_voice_pack", "companion_voice_digest").forEach {
            context.getSharedPreferences(it, Context.MODE_PRIVATE).edit().clear().commit()
        }
        File(context.filesDir, "voice-packs").deleteRecursively()
        voice = CompanionVoicePackManager(context)
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (request.path == "/slow.bin") MockResponse().setBody(Buffer().write(slowBytes))
                    .throttleBody(512, 250, TimeUnit.MILLISECONDS) // ~2 s
                else MockResponse().setResponseCode(404)
        }
    }

    @After fun tearDown() = server.shutdown()

    private fun pack(id: String, role: String, path: String, bytes: Long, sha: String) = JSONObject()
        .put("id", id).put("role", role).put("label", id).put("url", server.url(path).toString())
        .put("min_ram_mb", 1).put("size_bytes", bytes)
        .put("artifacts", JSONArray().put(JSONObject().put("filename", "model.bin")
            .put("url", server.url(path).toString()).put("sha256", sha).put("size_bytes", bytes)))

    private fun awaitRunning(packId: String, running: kotlinx.coroutines.Deferred<*>) {
        val deadline = System.currentTimeMillis() + 5_000
        while (!(packId in voice.downloadingPackIds() && voice.downloadProgress() in 1..99) &&
            !running.isCompleted && System.currentTimeMillis() < deadline) Thread.sleep(20)
        // Fail fast with the real cause if the download already died (e.g. a loopback connect
        // timeout to MockWebServer) instead of spinning out the 5 s window with no diagnosis.
        val earlyFailure = if (running.isCompleted) runCatching { runBlocking { running.await() } }.exceptionOrNull() else null
        assertTrue(
            "download of $packId should be running: ${voice.lastError()} ${voice.sttStatus()} progress=${voice.downloadProgress()} earlyFailure=$earlyFailure",
            packId in voice.downloadingPackIds(),
        )
    }

    private fun runRace(runningId: String) = runBlocking {
        val tts = CompanionVoicePackCatalog.POCKET_TTS_ID
        voice.updateCatalog(JSONObject().put("packs", JSONArray()
            .put(pack(runningId, "stt", "/slow.bin", slowBytes.size.toLong(), sha256(slowBytes)))
            .put(pack(tts, "tts", "/missing.bin", 10L, "00"))))
        val source = VoicePackSource(voice)
        val running = GlobalScope.async(Dispatchers.IO) { voice.downloadPack(runningId) }
        awaitRunning(runningId, running)
        val progressBefore = voice.downloadProgress()

        // Refresh from the downloaded-content page.
        source.entries()
        voice.refreshStatus()
        assertEquals(CompanionVoicePackStatus.DOWNLOADING, voice.sttStatus())

        // A second download that fails: same pack (already running) and another pack (404), both via the page.
        val runningRow = source.entries().single { it.name == runningId }
        assertTrue(runningRow.downloading)
        assertNotNull(runCatching { source.update(runningRow.copy(updateBytes = 1)) }.exceptionOrNull())
        val ttsRow = DownloadedEntry(ContentKind.VOICE, tts, tts, 0L, ContentState.PARTIAL, "", updateBytes = 10L)
        assertNotNull(runCatching { source.update(ttsRow) }.exceptionOrNull())

        assertTrue(running.isActive)
        assertTrue(runningId in voice.downloadingPackIds())
        assertEquals(CompanionVoicePackStatus.DOWNLOADING, voice.sttStatus())
        assertTrue("progress must not be reset by the failed download", voice.downloadProgress() >= progressBefore)

        running.await()
        assertEquals(100, voice.downloadProgress())
        assertTrue(voice.isPackInstalled(runningId))
    }

    @Test fun selected_pack_download_survives_refresh_and_failed_second_download() {
        runRace(voice.selectedSttPackId())
    }

    @Test fun unselected_pack_download_survives_refresh_and_failed_second_download() {
        val other = "stt-race-other"
        assertTrue(other != voice.selectedSttPackId())
        runRace(other)
    }

    /** Same role: while STT pack A downloads slowly, STT pack B fails (via the page and via downloadPack directly). */
    private fun sameRoleFailure(viaPage: Boolean) = runBlocking {
        val a = voice.selectedSttPackId()
        val b = "stt-race-broken"
        voice.updateCatalog(JSONObject().put("packs", JSONArray()
            .put(pack(a, "stt", "/slow.bin", slowBytes.size.toLong(), sha256(slowBytes)))
            .put(pack(b, "stt", "/missing.bin", 10L, "00"))))
        val source = VoicePackSource(voice)
        val running = GlobalScope.async(Dispatchers.IO) { voice.downloadPack(a) }
        awaitRunning(a, running)
        val aDir = File(voice.packRoot(), a)
        val errorBefore = voice.lastError()
        val second = GlobalScope.async(Dispatchers.IO) {
            runCatching {
                if (viaPage) source.update(DownloadedEntry(ContentKind.VOICE, b, b, 0L, ContentState.PARTIAL, "", updateBytes = 10L))
                else voice.downloadPack(b)
            }
        }
        var lastProgress = voice.downloadProgress()
        while (running.isActive) {
            assertEquals(CompanionVoicePackStatus.DOWNLOADING, voice.sttStatus())
            val now = voice.downloadProgress()
            assertTrue("A's progress dropped from $lastProgress to $now", now >= lastProgress)
            lastProgress = now
            assertEquals("B must not change lastError while A runs", errorBefore, voice.lastError())
            Thread.sleep(20)
        }
        running.await()
        val aFiles = aDir.walkTopDown().filter { it.isFile }.associate { it.name to it.readBytes().toList() }
        assertNotNull("B must fail", second.await().exceptionOrNull())
        assertEquals("B must not touch A's files", aFiles,
            aDir.walkTopDown().filter { it.isFile }.associate { it.name to it.readBytes().toList() })
        assertTrue(voice.isPackInstalled(a))
        voice.refreshStatus()
        assertEquals(CompanionVoicePackStatus.READY, voice.sttStatus())
        assertTrue(b !in voice.downloadingPackIds())
    }

    @Test fun same_role_failing_download_via_page_leaves_running_download_alone() = sameRoleFailure(viaPage = true)

    @Test fun same_role_failing_direct_download_leaves_running_download_alone() = sameRoleFailure(viaPage = false)
}