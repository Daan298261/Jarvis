package com.jarvis.companion

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import java.util.concurrent.CopyOnWriteArrayList

/**
 * RFC-0235 download entry points through the real [CompanionModel]: the Home status lines of
 * `installFastPhoneModel`, `error` and `busy` as `action {}` had them, and a side-effect-free
 * `selectCompanionPack`.
 */
@RunWith(KeystoreRobolectricRunner::class)
@Config(sdk = [34], application = JarvisApp::class, shadows = [ReplaceAtomicFileShadow::class])
class CompanionModelDownloadTest : CompanionModelHarness() {
    private fun recordStates(): CopyOnWriteArrayList<CompanionState> {
        val seen = CopyOnWriteArrayList<CompanionState>()
        CoroutineScope(Dispatchers.Unconfined).launch { model.state.collect { seen.add(it) } }
        return seen
    }

    @Test fun installFastPhoneModelPublishesTheHomeStatusLines() {
        pinFastModel(throttleMs = 20)
        val seen = recordStates()
        model.installFastPhoneModel()
        pump { model.state.value.activity == "Fast phone model ready" && !model.state.value.busy }
        val percentLines = seen.map { it.activity }.filter { it.startsWith("Downloading fast phone model · ") }
        assertTrue("Home shows the percent line: ${seen.map { it.activity }.distinct()}", percentLines.isNotEmpty() && percentLines.all { it.endsWith("%") })
        assertTrue(seen.any { it.localPackProgress in 1..99 })
        assertNull(model.state.value.error)
        assertEquals(ModelDownloadStage.READY, model.state.value.modelDownloads[fastId]?.stage)
    }

    @Test fun fastModelButtonIsDisabledWhileItsDownloadRuns() {
        pinFastModel(throttleMs = 20)
        val seen = recordStates()
        assertFalse(model.state.value.busy)
        model.installFastPhoneModel()
        assertTrue("busy from the moment the download starts", model.state.value.busy)
        pump { seen.any { it.activity.startsWith("Downloading fast phone model") } }
        // PhoneMemoryUi enables the button with `!state.busy`.
        assertTrue("${seen.map { it.activity to it.busy }.distinct()}", seen.any { it.busy && it.activity.startsWith("Downloading fast phone model") })
        pump { model.state.value.activity == "Fast phone model ready" && !model.state.value.busy }
    }

    @Test fun failedDownloadSetsErrorAndRetryClearsIt() {
        pinFastModel(hash = "0".repeat(64))
        model.downloadModelPack(fastId)
        pump { model.state.value.error != null && !model.state.value.busy }
        assertTrue(model.state.value.error!!.contains("checksum"))
        // The retry clears the last error when it starts, then succeeds.
        val seen = recordStates()
        pinFastModel()
        model.downloadModelPack(fastId)
        pump { model.state.value.modelDownloads[fastId]?.stage == ModelDownloadStage.READY && !model.state.value.busy }
        assertTrue("busy with the error already cleared", seen.any { it.busy && it.error == null })
        assertNull(model.state.value.error)
    }

    @Test fun failedFastModelInstallReachesStateError() {
        pinFastModel(hash = "f".repeat(64))
        model.installFastPhoneModel()
        pump { model.state.value.error != null && !model.state.value.busy }
        assertTrue(model.state.value.error!!.contains("checksum"))
        assertFalse(model.state.value.activity == "Fast phone model ready")
    }

    @Test fun selectCompanionPackLeavesErrorAndBusyUntouched() {
        model.action { error("A visible earlier error") }
        pump { model.state.value.error == "A visible earlier error" && !model.state.value.busy }
        val other = CompanionPackCatalog.builtIn.first { it.id != model.packManager.selectedPackId() }
        model.selectCompanionPack(other.id)
        pump { model.packManager.selectedPackId() == other.id }
        settle(500)
        val state = model.state.value
        assertEquals("the earlier error is not cleared", "A visible earlier error", state.error)
        assertFalse("the screen is not marked busy", state.busy)
        assertEquals(other.id, model.packManager.selectedPackId())
        pump { (context as JarvisApp).deviceModelChrome.state.value.selectedPackId == other.id }
    }
}
