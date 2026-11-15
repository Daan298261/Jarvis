package com.jarvis.companion

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** RFC-0235 criterion F: Downloaded content lists each non-ready model transfer with Cancel/Resume. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w411dp-h2400dp")
class DownloadedContentUiTest {
    @get:Rule val compose = createComposeRule()

    @Test fun downloadedContentShowsModelTransferRows() {
        val cancelled = mutableListOf<String>()
        val resumed = mutableListOf<String>()
        val running = ModelDownloadState("pack-a", "Qwen3 1.7B", ModelDownloadStage.DOWNLOADING, receivedBytes = 500_000_000, totalBytes = 1_000_000_000)
        val paused = ModelDownloadState("pack-b", "Qwen3 0.6B", ModelDownloadStage.PAUSED, receivedBytes = 100_000_000, totalBytes = 400_000_000)
        val failed = ModelDownloadState("pack-c", "Qwen3 4B", ModelDownloadStage.ERROR, detail = "Download needs a network connection")
        compose.setContent {
            DownloadedContentPage(DownloadedInventory(emptyList(), emptyList()), null, null, onUpdate = {}, onDelete = {}, onClose = {},
                modelDownloads = listOf(running, paused, failed), onCancelModel = { cancelled += it }, onResumeModel = { resumed += it })
        }
        compose.onNodeWithText("Qwen3 1.7B").assertExists()
        compose.onNodeWithText("Qwen3 0.6B").assertExists()
        compose.onNodeWithText("Qwen3 4B").assertExists()
        compose.onNodeWithText("Downloading · 50%").assertExists()
        compose.onNodeWithText("Paused · saved for resume").assertExists()
        compose.onNodeWithText("Download needs attention").assertExists()
        compose.onAllNodesWithText("Cancel download").assertCountEquals(1)
        compose.onNodeWithText("Cancel download").performClick()
        compose.onNodeWithText("Resume download").performClick()
        compose.onNodeWithText("Retry download").performClick()
        assertEquals(listOf("pack-a"), cancelled)
        assertEquals(listOf("pack-b", "pack-c"), resumed)
    }

    @Test fun noTransferRowsWhenNothingIsDownloading() {
        compose.setContent {
            DownloadedContentPage(DownloadedInventory(emptyList(), emptyList()), null, null, onUpdate = {}, onDelete = {}, onClose = {})
        }
        compose.onAllNodesWithText("Cancel download").assertCountEquals(0)
        compose.onAllNodesWithText("Resume download").assertCountEquals(0)
    }
}
