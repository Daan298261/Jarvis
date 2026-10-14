package com.jarvis.companion

import android.app.Activity
import android.content.Context
import android.view.WindowManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * RFC-0216 S1: owner control over screen capture. Default is blocked (FLAG_SECURE on) because
 * ANZU shows chats, notes and pairing material. Stored in the app's SharedPreferences pattern.
 */
object SecureScreenPrefs {
    const val PREFS = "secure_screen"
    const val KEY_ALLOW_SCREENSHOTS = "allow_screenshots"

    fun allowScreenshots(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_ALLOW_SCREENSHOTS, false)

    /** Returns false when the choice could not be persisted. */
    fun setAllowScreenshots(context: Context, allow: Boolean): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putBoolean(KEY_ALLOW_SCREENSHOTS, allow).commit()

    /** Preference false → FLAG_SECURE set; true → cleared. */
    fun apply(activity: Activity, allow: Boolean = allowScreenshots(activity)) {
        if (allow) activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        else activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }
}

/** Per-activity holder so the Settings row updates the live window without a restart. */
class SecureScreen(private val activity: Activity) {
    var allowScreenshots by mutableStateOf(SecureScreenPrefs.allowScreenshots(activity))
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { apply() }

    /** Re-read and re-apply (onResume), so the stored choice always wins. */
    fun apply() {
        allowScreenshots = SecureScreenPrefs.allowScreenshots(activity)
        SecureScreenPrefs.apply(activity, allowScreenshots)
    }

    fun change(allow: Boolean) {
        if (SecureScreenPrefs.setAllowScreenshots(activity, allow)) {
            error = null
            allowScreenshots = allow
            SecureScreenPrefs.apply(activity, allow)
        } else error = "Could not save the screenshot setting. Screen capture was not changed."
    }
}

@Composable
fun SecureScreenSettings(screen: SecureScreen) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Allow screenshots", Modifier.weight(1f))
            Switch(checked = screen.allowScreenshots, onCheckedChange = screen::change)
        }
        Text("Off by default: screenshots, screen recording and recent-apps previews are blocked to protect your chats and pairing codes.")
        screen.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}
