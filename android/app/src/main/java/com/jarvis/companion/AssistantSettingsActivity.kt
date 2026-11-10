package com.jarvis.companion

import android.app.Activity
import android.content.Intent
import android.os.Bundle

/** OEM assistant options forward to the normal protected app UI. */
class AssistantSettingsActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        startActivity(Intent(this, MainActivity::class.java).putExtra("anzu_assistant_settings", true)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
        finish()
    }
}
