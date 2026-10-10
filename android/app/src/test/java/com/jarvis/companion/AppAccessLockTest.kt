package com.jarvis.companion

import android.app.KeyguardManager
import android.app.Activity
import android.content.Intent
import android.content.Context
import android.os.Bundle
import android.provider.Settings
import android.view.WindowManager
import androidx.fragment.app.FragmentActivity
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

class AccessTestActivity : FragmentActivity() {
    lateinit var lock: AppAccessLock
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lock = AppAccessLock(this)
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29])
class AppAccessLockTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()

    @Before fun clearProtection() {
        context.getSharedPreferences("app_access", Context.MODE_PRIVATE).edit().clear().commit()
        shadowOf(context.getSystemService(KeyguardManager::class.java)).setIsDeviceSecure(false)
    }

    @Test fun opted_out_app_opens_without_authentication() {
        val activity = Robolectric.buildActivity(AccessTestActivity::class.java).setup().get()
        assertFalse(activity.lock.locked)
        assertEquals(0, activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE)
    }

    @Test fun stored_protection_starts_locked_and_blocks_screen_capture() {
        context.getSharedPreferences("app_access", Context.MODE_PRIVATE).edit().putBoolean("required", true).commit()
        val activity = Robolectric.buildActivity(AccessTestActivity::class.java).setup().get()
        assertTrue(activity.lock.locked)
        assertNotEquals(0, activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE)
        activity.lock.background()
        assertTrue(activity.lock.locked)
    }

    @Test fun enabling_requires_android_screen_lock_and_does_not_store_credentials() {
        val activity = Robolectric.buildActivity(AccessTestActivity::class.java).setup().get()
        activity.lock.changeProtection(true)
        assertFalse(activity.lock.enabled)
        assertEquals(Settings.ACTION_SECURITY_SETTINGS, shadowOf(activity).nextStartedActivity.action)
        assertTrue(activity.lock.error!!.contains("PIN"))
        assertTrue(context.getSharedPreferences("app_access", Context.MODE_PRIVATE).all.isEmpty())
    }

    @Test fun removing_phone_screen_lock_cannot_bypass_existing_protection() {
        context.getSharedPreferences("app_access", Context.MODE_PRIVATE).edit().putBoolean("required", true).commit()
        val activity = Robolectric.buildActivity(AccessTestActivity::class.java).setup().get()
        activity.lock.changeProtection(false)
        assertTrue(activity.lock.enabled)
        assertTrue(activity.lock.locked)
        assertTrue(context.getSharedPreferences("app_access", Context.MODE_PRIVATE).getBoolean("required", false))
    }

    @Test fun pin_success_enables_protection_and_background_requires_another_unlock() {
        val activity = Robolectric.buildActivity(AccessTestActivity::class.java).setup().get()
        val keyguard = shadowOf(activity.getSystemService(KeyguardManager::class.java))
        keyguard.setIsDeviceSecure(true)
        keyguard.setIsKeyguardSecure(true)
        activity.lock.changeProtection(true)
        val launched = shadowOf(activity).nextStartedActivityForResult
        assertNotNull(launched)
        activity.activityResultRegistry.dispatchResult(launched.requestCode, Activity.RESULT_OK, Intent())
        assertTrue(activity.lock.enabled)
        assertFalse(activity.lock.locked)
        assertEquals(setOf("required"), context.getSharedPreferences("app_access", Context.MODE_PRIVATE).all.keys)
        activity.lock.background()
        assertTrue(activity.lock.locked)
        activity.lock.unlock()
        val cancelled = shadowOf(activity).nextStartedActivityForResult
        activity.activityResultRegistry.dispatchResult(cancelled.requestCode, Activity.RESULT_CANCELED, Intent())
        assertTrue(activity.lock.locked)
        activity.lock.unlock()
        val accepted = shadowOf(activity).nextStartedActivityForResult
        activity.activityResultRegistry.dispatchResult(accepted.requestCode, Activity.RESULT_OK, Intent())
        assertFalse(activity.lock.locked)
        activity.lock.changeProtection(false)
        val disable = shadowOf(activity).nextStartedActivityForResult
        assertTrue(activity.lock.enabled)
        activity.activityResultRegistry.dispatchResult(disable.requestCode, Activity.RESULT_OK, Intent())
        assertFalse(activity.lock.enabled)
    }
}
