package com.jarvis.companion

import android.content.Intent
import android.net.Uri
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class SponsorCreditTest {
    @Test
    fun sponsor_credit_sentence_uses_em_dash() {
        assertEquals(
            "Made in the Netherlands \u2014 sponsored by Black Grid Publishing",
            AnzuBranding.SPONSOR_CREDIT,
        )
        assertEquals('\u2014', AnzuBranding.SPONSOR_CREDIT[AnzuBranding.SPONSOR_CREDIT.indexOf('\u2014')])
    }

    @Test
    fun sponsor_url_is_black_grid_publishing() {
        assertEquals("https://blackgridpublishing.com", AnzuBranding.SPONSOR_URL)
    }

    @Test
    fun browser_intent_is_action_view_for_sponsor_url() {
        val intent = SponsorCredit.browserIntent()
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals(Uri.parse(AnzuBranding.SPONSOR_URL), intent.data)
    }
}
