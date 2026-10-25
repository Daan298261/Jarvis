package com.jarvis.companion

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class AssistantRegistrationTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    @Test fun assistContextExcludesAllPasswordInputKinds() {
        val text = android.text.InputType.TYPE_CLASS_TEXT
        for (variation in listOf(0x80, 0x90, 0xe0)) assertTrue(isSensitiveAssistInput(text or variation))
        assertTrue(isSensitiveAssistInput(android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD))
        assertFalse(isSensitiveAssistInput(text or android.text.InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS))
    }
    @Test fun assistantOptionsResolveToRealPreferencesActivity() {
        val intent = Intent(Intent.ACTION_APPLICATION_PREFERENCES).setPackage(context.packageName)
        val match = context.packageManager.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
        assertEquals(AssistantSettingsActivity::class.java.name, match?.activityInfo?.name)
        val activity = org.robolectric.Robolectric.buildActivity(AssistantSettingsActivity::class.java).create().get()
        val forwarded = org.robolectric.Shadows.shadowOf(activity).nextStartedActivity
        assertEquals(MainActivity::class.java.name, forwarded.component?.className)
        assertTrue(forwarded.getBooleanExtra("anzu_assistant_settings", false))
        assertTrue(activity.isFinishing)
    }
    @Test fun systemVoiceButtonResolvesToAnzu() {
        val match = context.packageManager.resolveActivity(Intent(ANZU_VOICE_ASSIST_ACTION).setPackage(context.packageName), PackageManager.MATCH_DEFAULT_ONLY)
        assertNotNull(match)
        assertEquals(MainActivity::class.java.name, match!!.activityInfo.name)
    }
    @Test fun voiceMetadataHasRequiredRecognitionEndpointAndOptions() {
        val parser = context.resources.getXml(R.xml.anzu_voice_interaction)
        try {
            while (parser.next() != org.xmlpull.v1.XmlPullParser.START_TAG) { }
            val ns = "http://schemas.android.com/apk/res/android"
            assertEquals(AnzuRecognitionService::class.java.name, parser.getAttributeValue(ns, "recognitionService"))
            assertEquals("com.jarvis.companion.AssistantSettingsActivity", parser.getAttributeValue(ns, "settingsActivity"))
        } finally { parser.close() }
        val service = context.packageManager.getServiceInfo(ComponentName(context, AnzuRecognitionService::class.java), 0)
        assertEquals("android.permission.BIND_SPEECH_RECOGNITION_SERVICE", service.permission)
    }
}
