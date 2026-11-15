package com.jarvis.companion

import androidx.activity.ComponentActivity
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/**
 * RFC-0235 criterion E: Memory & speed shows the fast-model transfer view while it downloads and the
 * ready line once it is installed, rendered from the real [CompanionModel] state.
 */
@RunWith(KeystoreRobolectricRunner::class)
@Config(sdk = [34], application = JarvisApp::class, qualifiers = "w411dp-h4000dp-xxhdpi", shadows = [ReplaceAtomicFileShadow::class])
class PhoneMemoryUiTest : CompanionModelHarness() {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    @Test fun memorySpeedFastModelSectionShowsTransferAndReadyLine() {
        pinFastModel(throttleMs = 40)
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme()) { Surface {
                androidx.compose.foundation.layout.Column(Modifier.verticalScroll(rememberScrollState())) { PhoneMemorySettings(model) }
            } }
        }
        compose.onNodeWithText("Memory & speed").assertExists()
        compose.onNodeWithText("Download fast 0.6B model · 397 MB").assertExists()
        compose.onAllNodesWithText("Fast 0.6B model is ready · Quick answers can use it").let { assertTrue(it.fetchSemanticsNodes().isEmpty()) }
        model.installFastPhoneModel()
        // The transfer view (stage, Cancel) is shown while the download runs.
        pump { model.state.value.modelDownloads[fastId]?.active == true }
        compose.waitForIdle()
        assertTrue(compose.onAllNodesWithText("Cancel download").fetchSemanticsNodes().isNotEmpty())
        assertTrue(compose.onAllNodesWithText("Downloading", substring = true).fetchSemanticsNodes().isNotEmpty())
        // Once the download verified, the ready line replaces it.
        pump { model.state.value.activity == "Fast phone model ready" && !model.state.value.busy }
        pump(5_000) { compose.waitForIdle(); compose.onAllNodesWithText("Fast 0.6B model is ready · Quick answers can use it").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Fast 0.6B model is ready · Quick answers can use it").assertExists()
        assertTrue(compose.onAllNodesWithText("Cancel download").fetchSemanticsNodes().isEmpty())
    }
}
