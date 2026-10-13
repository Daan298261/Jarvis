package com.jarvis.companion

import android.app.Activity
import android.content.Context
import android.os.Bundle
import android.view.WindowManager
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

class SecureScreenTestActivity : Activity() {
    lateinit var screen: SecureScreen
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        screen = SecureScreen(this)
    }
    override fun onResume() { super.onResume(); screen.apply() }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29])
class SecureScreenPrefsTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private fun secure(a: Activity) = a.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0

    @Before fun clear() {
        context.getSharedPreferences(SecureScreenPrefs.PREFS, Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test fun fresh_install_blocks_screenshots() {
        assertFalse(SecureScreenPrefs.allowScreenshots(context))
        val a = Robolectric.buildActivity(SecureScreenTestActivity::class.java).setup().get()
        assertFalse(a.screen.allowScreenshots)
        assertTrue(secure(a))
    }

    @Test fun toggle_clears_and_restores_flag_live_and_persists() {
        val a = Robolectric.buildActivity(SecureScreenTestActivity::class.java).setup().get()
        a.screen.change(true)
        assertFalse(secure(a))
        assertTrue(SecureScreenPrefs.allowScreenshots(context))
        a.screen.change(false)
        assertTrue(secure(a))
        assertFalse(SecureScreenPrefs.allowScreenshots(context))
        assertNull(a.screen.error)
    }

    @Test fun stored_allow_survives_process_death_and_new_activity() {
        val first = Robolectric.buildActivity(SecureScreenTestActivity::class.java).setup()
        first.get().screen.change(true)
        first.pause().stop().destroy()
        val second = Robolectric.buildActivity(SecureScreenTestActivity::class.java).setup().get()
        assertTrue(second.screen.allowScreenshots)
        assertFalse(secure(second))
    }

    @Test fun resume_reapplies_stored_choice() {
        val c = Robolectric.buildActivity(SecureScreenTestActivity::class.java).setup()
        c.get().window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        c.pause().resume()
        assertTrue(secure(c.get()))
    }
}
