package com.jarvis.companion

import android.content.Intent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class VoicePackCreditTest {
    private val pocket = CompanionVoicePackCatalog.POCKET_TTS_ID

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

    @Test fun shippedPocketCatalogRowCarriesCredit() {
        val row = CompanionVoicePackCatalog.builtIn.first { it.id == pocket }
        assertEquals(CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION, VoicePackCredit.creditText(row.id, row.attribution))
    }

    @Test fun pocketCreditLinkOpensHuggingFaceInBrowser() {
        val url = VoicePackCredit.firstUrl(CompanionVoicePackCatalog.POCKET_VOICE_ATTRIBUTION)
        assertEquals("https://huggingface.co/kyutai/tts-voices#alba-mackenna", url)
        val intent = VoicePackCredit.browserIntent(url!!)
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals(url, intent.dataString)
    }

    @Test fun creditWithoutUrlIsNotALink() = assertNull(VoicePackCredit.firstUrl("Voice: Example (CC BY 4.0)."))
}
