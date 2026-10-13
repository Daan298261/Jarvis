package com.jarvis.companion

import android.webkit.WebResourceRequest
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToKey
import androidx.compose.ui.test.hasScrollToKeyAction
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** RFC-0216 S2 acceptance: pylon → picker; nothing downloads until a non-empty, storage-checked confirm. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class OffGridPickerUiTest {
    @get:Rule val compose = createComposeRule()
    private val catalog = OffGridContentCatalog.builtIn
    private val water = catalog.first { it.id == "zim-water" }
    private val knots = catalog.first { it.id == "zim-knots" }

    private fun host(free: Long, started: MutableList<List<String>>) = compose.setContent {
        var open by remember { mutableStateOf(false) }
        OffGridPylonEntry { open = true }
        if (open) OffGridPickerDialog(catalog, emptyMap(), free, onDismiss = { open = false }) { ids ->
            open = false; started += ids
        }
    }

    private fun pick(item: OffGridItem) {
        compose.onNode(hasScrollToKeyAction()).performScrollToKey(item.id)
        compose.onNodeWithText(item.title).performClick()
    }

    @Test fun pylon_opens_picker_and_download_disabled_until_selection() {
        val started = mutableListOf<List<String>>()
        host(Long.MAX_VALUE, started)
        compose.onNodeWithText("Select what to download", substring = true).assertDoesNotExist()
        compose.onNodeWithContentDescription("Power pylon: choose off-grid content").performClick()
        compose.onNodeWithText("Select what to download", substring = true).assertExists()
        compose.onNodeWithText("Select items").assertIsNotEnabled()
        compose.onNodeWithText("Close").performClick()
        compose.onNodeWithText("Select what to download", substring = true).assertDoesNotExist()
        assertTrue(started.isEmpty())
    }

    @Test fun confirm_passes_exactly_picked_items_and_back_starts_nothing() {
        val started = mutableListOf<List<String>>()
        host(Long.MAX_VALUE, started)
        compose.onNodeWithContentDescription("Power pylon: choose off-grid content").performClick()
        pick(water)
        pick(knots)
        compose.onNodeWithText(knots.title).performClick() // deselect
        compose.onNodeWithText("Download ${OffGridSelection.formatBytes(water.sizeBytes)}").assertIsEnabled().performClick()
        compose.onNodeWithText("• ${water.title}: ${OffGridSelection.formatBytes(water.sizeBytes)}").assertExists()
        compose.onNodeWithText("Back").performClick()
        assertTrue(started.isEmpty())
        compose.onNodeWithText("Download ${OffGridSelection.formatBytes(water.sizeBytes)}").performClick()
        compose.onNodeWithText("Download").performClick()
        assertEquals(listOf(listOf(water.id)), started)
    }

    @Test fun confirm_disabled_when_storage_short() {
        val started = mutableListOf<List<String>>()
        host(1_000L, started)
        compose.onNodeWithContentDescription("Power pylon: choose off-grid content").performClick()
        pick(water)
        compose.onNodeWithText("Download ${OffGridSelection.formatBytes(water.sizeBytes)}").performClick()
        compose.onNodeWithText("Not enough storage", substring = true).assertExists()
        compose.onNodeWithText("Download").assertIsNotEnabled()
        assertTrue(started.isEmpty())
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ZimReaderGuardTest {
    private fun request(url: String) = object : WebResourceRequest {
        override fun getUrl(): Uri = Uri.parse(url)
        override fun isForMainFrame() = true
        override fun isRedirect() = false
        override fun hasGesture() = false
        override fun getMethod() = "GET"
        override fun getRequestHeaders(): Map<String, String> = emptyMap()
    }

    @Test fun closed_source_refuses_reads_without_touching_archive() {
        var reads = 0; var disposed = 0
        val source = GuardedZimSource({ reads++; "hi".toByteArray() to "text/html" }) { disposed++ }
        assertNotNull(source.load("A/Page"))
        source.close(); source.close()
        assertNull(source.load("A/Page"))
        assertEquals(1, reads); assertEquals(1, disposed)
    }

    @Test fun webview_client_serves_archive_404s_after_close_and_blocks_network() {
        val source = GuardedZimSource({ "<p>ok</p>".toByteArray() to "text/html; charset=utf-8" }) {}
        val client = ZimWebViewClient(source) {}
        val web = android.webkit.WebView(androidx.test.core.app.ApplicationProvider.getApplicationContext())
        val ok = client.shouldInterceptRequest(web, request(ZimUrls.forPath("A/Page")))
        assertEquals(200, ok.statusCode); assertEquals("text/html", ok.mimeType)
        assertEquals(403, client.shouldInterceptRequest(web, request("https://example.com/x.js")).statusCode)
        source.close()
        assertEquals(404, client.shouldInterceptRequest(web, request(ZimUrls.forPath("A/Page"))).statusCode)
    }
}
