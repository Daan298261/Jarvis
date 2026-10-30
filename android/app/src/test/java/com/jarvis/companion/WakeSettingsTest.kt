package com.jarvis.companion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class WakeSettingsTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    @Before fun reset() { context.getSharedPreferences("anzu_assistant", 0).edit().clear().commit() }
    @Test fun stoppingDuringCooldownReportsWakeOff() {
        val service = org.robolectric.Robolectric.buildService(AnzuWakeService::class.java).create()
        WakeAudioState.status.value = "Wake listening cooling down"
        service.destroy()
        assertEquals("Wake word off", WakeAudioState.status.value)
    }
    @Test fun allRequestedAliasesUsePackagedModelTokens() {
        val keywords = WakeSettings(context).keywords(context)
        for (name in listOf("ANZU", "ANOE", "ENZO", "ANZOO", "AANZO", "JARVIS", "HEY_ANZU", "HEY_JARVIS")) {
            assertTrue(name, keywords.lineSequence().any { it.endsWith("@$name") })
        }
        assertFalse(keywords.contains("<unk>"))
    }
    @Test fun customDictionaryPhraseCompilesAndDeduplicates() {
        val keywords = WakeSettings(context).keywords(context, "hello jarvis, HELLO JARVIS")
        assertEquals(1, keywords.trim().lines().size)
        assertTrue(keywords.endsWith("@HELLO_JARVIS\n"))
    }
    @Test fun settingsPersistAndThresholdIsBounded() {
        val settings = WakeSettings(context)
        assertFalse(settings.enabled)
        assertFalse(settings.screenContext)
        assertEquals(0.15f, settings.threshold)
        settings.enabled = true; settings.phrases = "jarvis"; settings.threshold = 9f; settings.screenContext = true
        val restored = WakeSettings(context)
        assertTrue(restored.enabled); assertTrue(restored.screenContext)
        assertEquals("jarvis", restored.phrases); assertEquals(0.6f, restored.threshold)
        restored.threshold = -1f; assertEquals(0.05f, restored.threshold)
    }
    @Test fun malformedOrUnknownPhrasesCannotReachNativeParser() {
        for (phrase in listOf("", "jarvis #0.01", "nonsensewordzz", "@JARVIS", "a b c d e")) {
            assertTrue(phrase, runCatching { WakeSettings(context).keywords(context, phrase) }.isFailure)
        }
    }
}
