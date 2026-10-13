package com.jarvis.companion

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest

class OffGridCatalogTest {
    @Test fun builtin_catalog_is_pinned_and_covers_rfc_categories() {
        val items = OffGridContentCatalog.builtIn
        OffGridContentCatalog.validate(items)
        assertEquals(OffGridCategory.entries.toSet(), items.map { it.category }.toSet())
        items.filter { !it.isMap }.forEach {
            assertTrue(it.url, it.url.startsWith("https://download.kiwix.org/zim/"))
            assertTrue(it.sha256.matches(Regex("[0-9a-f]{64}")))
            assertTrue(it.version.matches(Regex("\\d{4}-\\d{2}")))
        }
        items.filter { it.isMap }.forEach { assertEquals(OffGridContentCatalog.MAP_STYLE_URL, it.url) }
    }

    @Test fun empty_url_fails_validation() {
        val bad = OffGridContentCatalog.builtIn.first { !it.isMap }.copy(url = "")
        assertThrows(IllegalArgumentException::class.java) { OffGridContentCatalog.validate(listOf(bad)) }
    }

    @Test fun zim_without_hash_or_http_url_fails() {
        val zim = OffGridContentCatalog.builtIn.first { !it.isMap }
        assertThrows(IllegalArgumentException::class.java) { OffGridContentCatalog.validate(listOf(zim.copy(sha256 = ""))) }
        assertThrows(IllegalArgumentException::class.java) { OffGridContentCatalog.validate(listOf(zim.copy(url = zim.url.replace("https", "http")))) }
        assertThrows(IllegalArgumentException::class.java) { OffGridContentCatalog.validate(listOf(zim.copy(sizeBytes = 0))) }
    }

    @Test fun selection_totals_large_confirm_and_storage() {
        val small = OffGridContentCatalog.builtIn.first { it.id == "zim-water" }
        val big = OffGridContentCatalog.builtIn.first { it.id == "zim-trueprepper" }
        assertFalse(OffGridSelection.needsLargeConfirm(listOf(small)))
        assertTrue(OffGridSelection.needsLargeConfirm(listOf(small, big)))
        assertEquals(small.sizeBytes + big.sizeBytes, OffGridSelection.totalBytes(listOf(small, big)))
        assertNull(OffGridSelection.storageBlockReason(10_000_000_000L, listOf(big)))
        assertNotNull(OffGridSelection.storageBlockReason(big.sizeBytes, listOf(big)))
        // Resumable bytes already on disk count toward what is needed.
        assertNull(OffGridSelection.storageBlockReason(OffGridSelection.STORAGE_MARGIN_BYTES + 10, listOf(small), small.sizeBytes - 10))
        assertEquals("1.4 GB", OffGridSelection.formatBytes(big.sizeBytes))
        assertEquals("21 MB", OffGridSelection.formatBytes(small.sizeBytes))
    }

    @Test fun map_tile_count_is_web_mercator() {
        assertEquals(1L, OffGridMapMath.tileCount(OffGridMapRegion(-1.0, -1.0, 1.0, 1.0, 0, 0)))
        assertEquals(1L + 4L, OffGridMapMath.tileCount(OffGridMapRegion(-1.0, -1.0, 1.0, 1.0, 0, 1)))
        val nl = OffGridContentCatalog.builtIn.first { it.id == "map-nl" }.mapRegion!!
        assertTrue(OffGridMapMath.tileCount(nl) in 40_000L..60_000L)
        assertTrue(OffGridMapMath.tileCount(nl) < MapLibreMapStore.TILE_LIMIT)
    }

    @Test fun map_status_never_ready_until_complete() {
        assertEquals(OffGridStatus.DOWNLOADING, OffGridMapStatus.of(false, true, 100, 100).status)
        assertEquals(99, OffGridMapStatus.of(false, true, 100, 100).progress)
        assertEquals(OffGridStatus.READY, OffGridMapStatus.of(true, false, 100, 100).status)
        assertEquals(OffGridStatus.MISSING, OffGridMapStatus.of(false, false, 10, 100).status)
        assertEquals(OffGridStatus.ERROR, OffGridMapStatus.of(false, true, 10, 100, "boom").status)
    }
}

class OffGridContentManagerTest {
    @get:Rule val tmp = TemporaryFolder()
    private val server = MockWebServer()
    private val payload = ByteArray(300_000) { (it * 31 % 251).toByte() }
    private val sha = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }

    private class FakeMaps : OffGridMapStore {
        val calls = mutableListOf<String>()
        override suspend fun states(items: List<OffGridItem>) = items.associate { it.id to OffGridItemState() }
        override suspend fun download(item: OffGridItem, onState: (OffGridItemState) -> Unit) {
            calls += "download:${item.id}"; onState(OffGridItemState(OffGridStatus.READY, 100))
        }
        override suspend fun pause(item: OffGridItem) { calls += "pause:${item.id}" }
        override suspend fun delete(item: OffGridItem) { calls += "delete:${item.id}" }
    }

    @Before fun start() = server.start()
    @After fun stop() = server.shutdown()

    private fun zim(hash: String = sha) = OffGridItem("zim-test", "Test ZIM", OffGridCategory.SURVIVAL, payload.size.toLong(), hash,
        server.url("/zim/test_2026-01.zim").toString())

    private fun manager(item: OffGridItem, maps: OffGridMapStore = FakeMaps(), free: Long = Long.MAX_VALUE) = OffGridContentManager(
        root = tmp.newFolder(), digestCache = VerifiedDigestCache(), mapStore = maps, catalog = listOf(item),
        freeBytes = { free }, retrySleep = {}, urlScheme = "http://",
    )

    @Test fun picked_zim_downloads_verifies_and_is_ready() = runBlocking {
        server.enqueue(MockResponse().setBody(Buffer().write(payload)))
        val m = manager(zim())
        m.download("zim-test")
        assertEquals(OffGridStatus.READY, m.stateOf("zim-test").status)
        assertArrayEquals(payload, m.verifiedZim("zim-test").readBytes())
        assertEquals(1, server.requestCount)
    }

    @Test fun corrupt_hash_is_error_never_ready_and_retry_succeeds() = runBlocking {
        val corrupt = payload.copyOf().also { it[10] = (it[10] + 1).toByte() }
        server.enqueue(MockResponse().setBody(Buffer().write(corrupt)))
        server.enqueue(MockResponse().setBody(Buffer().write(payload)))
        val m = manager(zim())
        m.download("zim-test")
        assertEquals(OffGridStatus.ERROR, m.stateOf("zim-test").status)
        assertTrue(m.stateOf("zim-test").error!!.contains("checksum"))
        assertFalse(m.file(m.item("zim-test")).exists())
        assertThrows(IllegalStateException::class.java) { runBlocking { m.verifiedZim("zim-test") } }
        m.download("zim-test")
        assertEquals(OffGridStatus.READY, m.stateOf("zim-test").status)
    }

    @Test fun interrupted_download_resumes_with_range() = runBlocking {
        val half = payload.size / 2
        server.enqueue(MockResponse().setBody(Buffer().write(payload, 0, half)).setHeader("Content-Length", payload.size)
            .setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY))
        server.enqueue(MockResponse().setResponseCode(206).setBody(Buffer().write(payload, half, payload.size - half)))
        val m = manager(zim())
        // First attempt drops; TransientRetry resumes from the partial with a Range header.
        server.dispatcher = object : okhttp3.mockwebserver.Dispatcher() {
            var n = 0
            override fun dispatch(request: okhttp3.mockwebserver.RecordedRequest): MockResponse {
                n++
                val range = request.getHeader("Range")
                if (range == null) return MockResponse().setBody(Buffer().write(payload, 0, half))
                    .setHeader("Content-Length", payload.size).setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY)
                val from = range.removePrefix("bytes=").removeSuffix("-").toInt()
                return MockResponse().setResponseCode(206).setBody(Buffer().write(payload, from, payload.size - from))
            }
        }
        m.download("zim-test")
        assertEquals(OffGridStatus.READY, m.stateOf("zim-test").status)
        assertArrayEquals(payload, m.verifiedZim("zim-test").readBytes())
    }

    @Test fun cancel_mid_download_leaves_no_ready_file() = runBlocking {
        server.enqueue(MockResponse().setBody(Buffer().write(payload)).throttleBody(16_000, 50, java.util.concurrent.TimeUnit.MILLISECONDS))
        val m = manager(zim())
        val job = launch(Dispatchers.IO) { m.download("zim-test") }
        withTimeout(10_000) { while (m.stateOf("zim-test").progress < 5) delay(20) }
        job.cancel(); job.join()
        val s = m.stateOf("zim-test")
        assertNotEquals(OffGridStatus.READY, s.status)
        assertFalse(m.file(m.item("zim-test")).exists())
        assertTrue(s.partialBytes in 1 until payload.size)
    }

    @Test fun storage_preflight_blocks_without_network() = runBlocking {
        val m = manager(zim(), free = 1_000L)
        m.download("zim-test")
        assertEquals(OffGridStatus.ERROR, m.stateOf("zim-test").status)
        assertTrue(m.stateOf("zim-test").error!!.contains("storage"))
        assertEquals(0, server.requestCount)
    }

    @Test fun tampered_file_fails_closed_on_open() = runBlocking {
        server.enqueue(MockResponse().setBody(Buffer().write(payload)))
        val m = manager(zim())
        m.download("zim-test")
        val f = m.file(m.item("zim-test"))
        f.appendBytes(byteArrayOf(1))
        assertThrows(IllegalStateException::class.java) { runBlocking { m.verifiedZim("zim-test") } }
        assertEquals(OffGridStatus.ERROR, m.stateOf("zim-test").status)
        m.refresh()
        assertEquals(OffGridStatus.ERROR, m.stateOf("zim-test").status)
    }

    @Test fun delete_removes_file_and_partial() = runBlocking {
        server.enqueue(MockResponse().setBody(Buffer().write(payload)))
        val m = manager(zim())
        m.download("zim-test")
        m.delete("zim-test")
        assertFalse(m.file(m.item("zim-test")).exists())
        assertEquals(OffGridStatus.MISSING, m.stateOf("zim-test").status)
    }

    @Test fun map_items_go_through_map_store() = runBlocking {
        val maps = FakeMaps()
        val map = OffGridContentCatalog.builtIn.first { it.id == "map-lu" }
        val m = OffGridContentManager(tmp.newFolder(), VerifiedDigestCache(), maps, listOf(map), freeBytes = { Long.MAX_VALUE })
        m.download("map-lu")
        assertEquals(OffGridStatus.READY, m.stateOf("map-lu").status)
        m.delete("map-lu")
        assertEquals(listOf("download:map-lu", "delete:map-lu"), maps.calls)
    }
}
