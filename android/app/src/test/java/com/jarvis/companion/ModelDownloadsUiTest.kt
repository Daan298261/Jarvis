package com.jarvis.companion

import android.graphics.Bitmap
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w411dp-h891dp-xxhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ModelDownloadsUiTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    @Test fun downloadHasImmediateFeedbackAndCanBePausedAndResumed() {
        val transfer = mutableStateOf<ModelDownloadState?>(null)
        var starts = 0
        val pack = DevicePackOption("test", "Qwen3 1.7B Abliterated", 1_107_409_024, 2048)
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFF5A623))) {
                Surface {
                    ModelLibraryCards(listOf(pack), "test", transfer.value?.let { mapOf("test" to it) } ?: emptyMap(), false,
                        onSelect = {}, onDownload = { starts++; transfer.value = ModelDownloadState("test", pack.label, totalBytes = pack.sizeBytes) },
                        onCancel = { transfer.value = transfer.value?.copy(stage = ModelDownloadStage.PAUSED, receivedBytes = 100_000_000) })
                }
            }
        }
        compose.onNodeWithText("Download model").performClick()
        compose.onNodeWithText("Connecting…").assertExists()
        compose.onNodeWithText("Download model").assertDoesNotExist()
        compose.onNodeWithText("Cancel download").performClick()
        compose.onNodeWithText("Paused · saved for resume").assertExists()
        compose.onNodeWithText("Resume download").performClick()
        compose.runOnIdle { assertEquals(2, starts) }
        compose.onNodeWithText("Connecting…").assertExists()
    }

    @Test fun renderModelCardsWithDownloadProgress() {
        compose.mainClock.autoAdvance = false
        val id = CompanionPackCatalog.ABLITERATED_17B_ID
        val transfer = ModelDownloadState(id, "Qwen3 1.7B Abliterated", ModelDownloadStage.DOWNLOADING,
            receivedBytes = 512_000_000, totalBytes = 1_107_409_024, bytesPerSecond = 4_000_000)
        compose.setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFF5A623), background = Color(0xFF080C12), surface = Color(0xFF111A26))) {
                Surface(Modifier.fillMaxSize()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Models on this phone", style = MaterialTheme.typography.headlineSmall)
                        Text("Download once, then chat without your desktop.")
                        ModelLibraryCards(listOf(DevicePackOption(id, transfer.label, transfer.totalBytes, 2048),
                            DevicePackOption(CompanionPackCatalog.ABLITERATED_06B_ID, "Qwen3 0.6B Abliterated", 396_704_896, 1024)),
                            id, mapOf(id to transfer), false, {}, {}, {})
                    }
                }
            }
        }
        compose.onNodeWithText("Downloading · 46%").assertExists()
        compose.onNodeWithText("Cancel download").assertExists()
        compose.runOnIdle {
            val view = compose.activity.window.decorView
            val image = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(android.graphics.Canvas(image))
            val output = File("build/reports/model-downloads/model-library.png")
            output.parentFile?.mkdirs()
            output.outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
}
