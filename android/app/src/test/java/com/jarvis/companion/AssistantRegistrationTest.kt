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
