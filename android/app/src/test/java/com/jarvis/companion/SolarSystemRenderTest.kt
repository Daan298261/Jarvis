package com.jarvis.companion

import android.graphics.Bitmap
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.test.core.app.ApplicationProvider
import java.io.File
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class SolarSystemRenderTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    @Test fun renderSolarSystemWithContextDescription() {
        Settings.Global.putFloat(ApplicationProvider.getApplicationContext<android.content.Context>().contentResolver,
            Settings.Global.ANIMATOR_DURATION_SCALE, 0f)
        compose.mainClock.autoAdvance = false
        val context = mutableStateOf(0f)
        compose.setContent { Box(Modifier.background(Color(0xFF080C12))) {
            PresenceHud("orb", PresencePhase.THINKING, contextUsed = context.value)
        } }
        for (percent in listOf(0, 50, 100)) {
            compose.runOnIdle { context.value = percent / 100f }
            compose.mainClock.advanceTimeByFrame()
            val node = compose.onNodeWithContentDescription(
                "Solar system: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, Neptune. Phone context $percent percent used")
            node.assertExists()
            compose.runOnIdle {
                val view = compose.activity.window.decorView
                val image = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
                view.draw(android.graphics.Canvas(image))
                val output = File("build/reports/solar-system/context-$percent.png")
                output.parentFile?.mkdirs()
                output.outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
            }
        }
    }
}
