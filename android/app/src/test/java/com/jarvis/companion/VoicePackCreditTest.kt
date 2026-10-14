package com.jarvis.companion

import android.app.Application
import android.content.Intent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class VoicePackCreditTest {
    @get:Rule val compose = createComposeRule()
    private val app: Application = ApplicationProvider.getApplicationContext()
    private val pocket = CompanionVoicePackCatalog.POCKET_TTS_ID
    private val pocketUrls = listOf(
        "https://huggingface.co/kyutai/tts-voices#alba-mackenna",
        "https://creativecommons.org/licenses/by/4.0/",
        "https://huggingface.co/kyutai/pocket-tts",
        "https://huggingface.co/soniqo/Pocket-TTS-100M-ONNX-INT8",
    )

    @Test fun normalAttributionIsShownAsIs() =
        assertEquals("Voice: Example (CC BY 4.0).", VoicePackCredit.creditText("other-tts", "  Voice: Example (CC BY 4.0). "))

    @Test fun blankPocketAttributionFallsBackToPinnedCredit() =
        assertEquals(CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION, VoicePackCredit.creditText(pocket, "   "))

    @Test fun missingPocketAttributionFallsBackToPinnedCredit() =
        assertEquals(CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION, VoicePackCredit.creditText(pocket, null))

    @Test fun nonPocketPackWithoutAttributionHasNoCredit() {
        assertNull(VoicePackCredit.creditText("whisper-tiny-en-cpp", ""))
        assertNull(VoicePackCredit.creditText("whisper-tiny-en-cpp", null))
    }

    @Test fun pocketCreditCarriesLicenceModelAndModificationNotice() {
        val credit = CompanionVoicePackCatalog.builtIn.first { it.id == pocket }.attribution
        assertEquals(pocketUrls, VoicePackCredit.urls(credit))
        assertTrue(credit.contains("CC BY 4.0"))
        assertTrue(credit.contains("Modified: converted to ONNX INT8 by soniqo"))
        assertFalse(VoicePackCredit.sentence(credit).contains("https://"))
    }

    @Test fun pocketCreditShowsWhenInstalledEvenIfAnotherPackIsSelected() {
        assertTrue(VoicePackCredit.shouldShow(pocket, selectedId = "other-tts", installed = true))
        assertTrue(VoicePackCredit.shouldShow(pocket, selectedId = pocket, installed = false))
        assertFalse(VoicePackCredit.shouldShow(pocket, selectedId = "other-tts", installed = false))
        assertTrue(VoicePackCredit.shouldShow("other-tts", selectedId = "other-tts", installed = false))
        assertFalse(VoicePackCredit.shouldShow("other-tts", selectedId = pocket, installed = true))
    }

    @Test fun sponsorBrowserIntentDefaultStillOpensSponsorSite() =
        assertEquals(AnzuBranding.SPONSOR_URL, SponsorCredit.browserIntent().dataString)

    @Test fun creditWithoutUrlHasNoLinks() = assertTrue(VoicePackCredit.urls("Voice: Example (CC BY 4.0).").isEmpty())

    @Test fun renderedPocketCreditIsVisibleAndEveryLinkOpensItsUrl() {
        compose.setContent { VoicePackCreditText(pocket, "", color = Color.Gray, errorColor = Color.Red) }
        compose.onNodeWithText(VoicePackCredit.sentence(CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION)).assertIsDisplayed()
        for (url in pocketUrls) {
            val label = app.getString(VoicePackCredit.linkLabel(url))
            val node = compose.onNodeWithText("$label: $url")
            node.assertIsDisplayed()
            val semantics = node.fetchSemanticsNode().config
            assertEquals(Role.Button, semantics[SemanticsProperties.Role])
            assertEquals(label, semantics[SemanticsActions.OnClick].label)
            node.performClick()
            val started = shadowOf(app).nextStartedActivity
            assertEquals(Intent.ACTION_VIEW, started.action)
            assertEquals(url, started.dataString)
        }
    }
}
