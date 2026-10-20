package com.jarvis.companion

import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * RFC-0235 download feedback is layered on top of the live Models screen and first-run setup card:
 * the status line, pack dropdown, Download/Re-download, Delete and file import must all stay.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w411dp-h2400dp-xxhdpi")
class ModelScreensLiveUiTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    private val installedId = CompanionPackCatalog.ABLITERATED_17B_ID
    private val otherId = CompanionPackCatalog.ABLITERATED_06B_ID
    private val packs = listOf(
        DevicePackOption(installedId, "Qwen3 1.7B Abliterated", 1_107_409_024, 2048, installed = true),
        DevicePackOption(otherId, "Qwen3 0.6B Abliterated", 396_704_896, 1024),
    )

    @Test fun modelsScreenKeepsStatusDropdownAndRedownloadWithProgressOnTop() {
        val chrome = CompanionDeviceModelChrome()
        var redownloads = 0
        chrome.actions = object : DevicePackChromeActions {
            override fun downloadSelectedPack() { redownloads++ }
            override fun deleteSelectedPack() {}
            override fun selectPack(packId: String) {}
        }
        val transfer = ModelDownloadState(installedId, packs[0].label, ModelDownloadStage.DOWNLOADING,
            receivedBytes = 553_704_512, totalBytes = 1_107_409_024)
        val devicePack = DevicePackChromeState(
            status = DevicePackStatus.READY, selectedPackId = installedId, selectedPackLabel = packs[0].label,
            bytesOnDisk = 1_107_409_024, availablePacks = packs, nativeRuntimeBundled = true,
        )
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme()) { Surface {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    CompanionModelsSection(chrome, devicePack, CompanionState(), pickModelFile = {})
                    CompanionModelsSection(chrome, devicePack.copy(downloads = mapOf(installedId to transfer)), CompanionState(), pickModelFile = {})
                }
            } }
        }
        // Live UI from development, still present in both renders.
        assertEquals(2, compose.onAllNodesWithText("Status · ready").fetchSemanticsNodes().size)
        assertEquals(2, compose.onAllNodesWithText("Re-download pack").fetchSemanticsNodes().size)
        assertEquals(2, compose.onAllNodesWithText("Delete pack").fetchSemanticsNodes().size)
        assertEquals(2, compose.onAllNodesWithText("Load model from file (.gguf)").fetchSemanticsNodes().size)
        compose.onAllNodesWithText("Re-download pack")[0].performClick()
        compose.runOnIdle { assertEquals(1, redownloads) }
        val before = compose.onAllNodesWithText("Qwen3 0.6B Abliterated").fetchSemanticsNodes().size
        compose.onAllNodesWithText("Pack · Qwen3 1.7B Abliterated ▾")[0].performClick()
        // The pack dropdown opens and lists the other pack (one more node than the cards alone).
        assertEquals(before + 1, compose.onAllNodesWithText("Qwen3 0.6B Abliterated").fetchSemanticsNodes().size)
        // RFC-0235 progress layered on top, only in the render with a tracked transfer: once in the
        // status card and once on that model's card.
        assertEquals(2, compose.onAllNodesWithText("Downloading · 50%").fetchSemanticsNodes().size)
        assertTrue(compose.onAllNodesWithText("Cancel download").fetchSemanticsNodes().isNotEmpty())
    }

    @Test fun setupCardKeepsDownloadButtonWhileShowingTransferFeedback() {
        val chrome = CompanionDeviceModelChrome()
        var downloads = 0
        chrome.actions = object : DevicePackChromeActions {
            override fun downloadSelectedPack() { downloads++ }
            override fun deleteSelectedPack() {}
            override fun selectPack(packId: String) {}
        }
        val paused = ModelDownloadState(otherId, packs[1].label, ModelDownloadStage.PAUSED,
            receivedBytes = 100_000_000, totalBytes = 396_704_896)
        val devicePack = DevicePackChromeState(status = DevicePackStatus.MISSING, selectedPackId = otherId,
            selectedPackLabel = packs[1].label, availablePacks = packs, downloads = mapOf(otherId to paused))
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme()) { Surface {
                PhoneSetupCard(CompanionState(), devicePack, chrome, pickModelFile = {})
            } }
        }
        compose.onNodeWithText("Paused · saved for resume").assertExists()
        compose.onNodeWithText("Resume download").assertExists()
        compose.onNodeWithText("Load from file").assertExists()
        compose.onNodeWithText("Download model").performClick()
        compose.runOnIdle { assertEquals(1, downloads) }
    }

    private val determinateBar = SemanticsMatcher("determinate progress bar") {
        val info = it.config.getOrNull(SemanticsProperties.ProgressBarRangeInfo)
        info != null && info != ProgressBarRangeInfo.Indeterminate
    }

    /** D2 #671 item 1: development's bar and percent text stay during a tracked download; no second bar. */
    @Test fun legacyProgressStaysVisibleDuringATrackedDownload() {
        val chrome = CompanionDeviceModelChrome()
        val transfer = ModelDownloadState(otherId, packs[1].label, ModelDownloadStage.DOWNLOADING,
            receivedBytes = 166_616_056, totalBytes = 396_704_896)
        val devicePack = DevicePackChromeState(status = DevicePackStatus.DOWNLOADING, selectedPackId = otherId,
            selectedPackLabel = packs[1].label, availablePacks = packs, downloadProgress = 0.42f,
            downloads = mapOf(otherId to transfer))
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme()) { Surface {
                PhoneSetupCard(CompanionState(localPackProgress = 42), devicePack, chrome, pickModelFile = {})
            } }
        }
        compose.onNodeWithText("Downloading… 42%").assertExists()
        compose.onNodeWithText("Downloading · 42%").assertExists()
        compose.onNodeWithText("Cancel download").assertExists()
        assertEquals(1, compose.onAllNodes(determinateBar).fetchSemanticsNodes().size)
    }

    @Test fun modelsCardKeepsLegacyPercentDuringATrackedDownload() {
        val chrome = CompanionDeviceModelChrome()
        val transfer = ModelDownloadState(otherId, packs[1].label, ModelDownloadStage.DOWNLOADING,
            receivedBytes = 166_616_056, totalBytes = 396_704_896)
        val devicePack = DevicePackChromeState(status = DevicePackStatus.DOWNLOADING, selectedPackId = otherId,
            selectedPackLabel = packs[1].label, availablePacks = packs, downloadProgress = 0.42f,
            nativeRuntimeBundled = true, downloads = mapOf(otherId to transfer))
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme()) { Surface {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    CompanionModelsSection(chrome, devicePack, CompanionState(), pickModelFile = {})
                }
            } }
        }
        compose.onNodeWithText("42%").assertExists()
        // One bar in the status card (development's) and one on that model's library card; the
        // status card's transfer view adds no second bar.
        assertEquals(2, compose.onAllNodes(determinateBar).fetchSemanticsNodes().size)
    }
}
