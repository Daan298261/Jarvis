package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class PostPairPackOfferTest {
    private lateinit var context: Context

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.getSharedPreferences("companion_ui", Context.MODE_PRIVATE).edit().clear().apply()
    }

    @Test
    fun formatPackCatalogSizeMb_roundsPerRfc() {
        assertEquals("~1050 MB", formatPackCatalogSizeMb(1_050_000_000L))
        assertEquals("~1120 MB", formatPackCatalogSizeMb(1_119_500_000L))
    }

    @Test
    fun formatPackCatalogSizeMb_blankWhenUnknown() {
        assertEquals(null, formatPackCatalogSizeMb(0L))
    }

    @Test
    fun shouldOffer_untilHandled_orPackReady() {
        val deviceId = "device-abc"
        assertTrue(PostPairPackOfferPrefs.shouldOffer(context, deviceId, DevicePackStatus.MISSING))
        PostPairPackOfferPrefs.markHandled(context, deviceId)
        assertFalse(PostPairPackOfferPrefs.shouldOffer(context, deviceId, DevicePackStatus.MISSING))
        assertFalse(PostPairPackOfferPrefs.shouldOffer(context, deviceId, DevicePackStatus.READY))
        assertFalse(PostPairPackOfferPrefs.shouldOffer(context, "", DevicePackStatus.MISSING))
    }
}
