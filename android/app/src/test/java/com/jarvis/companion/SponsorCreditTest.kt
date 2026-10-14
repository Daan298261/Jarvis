package com.jarvis.companion

import android.app.Application
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.ApplicationInfo
import android.content.pm.ResolveInfo
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows

@RunWith(RobolectricTestRunner::class)
class SponsorCreditTest {
    private lateinit var app: Application

    @Before
    fun setUp() {
        app = ApplicationProvider.getApplicationContext()
        // Match production: startActivity throws ActivityNotFoundException with no handler.
        Shadows.shadowOf(app).checkActivities(true)
    }

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

    @Test
    fun openInBrowser_starts_action_view_when_handler_exists() {
        val resolveInfo = ResolveInfo().apply {
            activityInfo = ActivityInfo().apply {
                name = "com.example.BrowserActivity"
                packageName = "com.example.browser"
                exported = true
                applicationInfo = ApplicationInfo().apply {
                    packageName = "com.example.browser"
                }
            }
        }
        Shadows.shadowOf(app.packageManager).addResolveInfoForIntent(
            Intent(Intent.ACTION_VIEW, Uri.parse(AnzuBranding.SPONSOR_URL)),
            resolveInfo,
        )

        assertTrue(SponsorCredit.openInBrowser(app))

        val started = Shadows.shadowOf(app).nextStartedActivity
        assertNotNull(started)
        assertEquals(Intent.ACTION_VIEW, started.action)
        assertEquals(Uri.parse(AnzuBranding.SPONSOR_URL), started.data)
        assertTrue(started.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
    }

    @Test
    fun openInBrowser_returns_false_when_no_handler() {
        assertFalse(SponsorCredit.openInBrowser(app))
    }
}
