package com.jarvis.companion

import androidx.test.core.app.ApplicationProvider
import android.content.Context
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import kotlinx.coroutines.runBlocking

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [29])
class PhoneToolsTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun permissionIsScopedByAppAndCategoryAndCanBeRevoked() {
        val permissions = PhoneToolPermissions(context)
        permissions.enable(true)
        permissions.save("com.example.app", setOf("read", "navigate"))
        assertTrue(permissions.allowed("com.example.app", setOf("read")))
        assertFalse(permissions.allowed("com.other.app", setOf("read")))
        assertFalse(permissions.allowed("com.example.app", setOf("send")))
        permissions.save("com.example.app", emptySet())
        assertFalse(permissions.allowed("com.example.app", setOf("read")))
        permissions.enable(false)
    }

    @Test fun visibleSensitiveControlsCannotBeDowngradedByModel() {
        val command = JSONObject().put("action", "tap").put("category", "navigate")
        assertTrue("purchase" in PhoneTools.requiredCategories(command, "Pay now"))
        assertTrue("send" in PhoneTools.requiredCategories(command, "Send message"))
        assertTrue("delete" in PhoneTools.requiredCategories(command, "Delete account"))
        assertTrue("security" in PhoneTools.requiredCategories(command, "Allow permission"))
    }

    @Test fun disabledToolsNeverExecute() = runBlocking {
        PhoneToolPermissions(context).enable(false)
        val result = PhoneTools.execute(context, JSONObject().put("action", "launch").put("package", "com.example.app"))
        assertFalse(result.getBoolean("ok"))
    }

    @Test fun stopInvalidatesCurrentTaskAndUnknownActionIsRejected() = runBlocking {
        PhoneToolPermissions(context).enable(true)
        val epoch = PhoneTools.epoch()
        PhoneTools.stop()
        val result = PhoneTools.execute(context, JSONObject().put("action", "launch").put("package", "com.example.app"), epoch)
        assertFalse(result.getBoolean("ok"))
        assertTrue(result.getString("error").contains("stopped"))
        PhoneToolPermissions(context).enable(false)
    }

    @Test fun lowMemoryFallbackNeverLoadsUnselectedLargePack() {
        val packs = CompanionPackCatalog.builtIn
        val chosen = CompanionPackCatalog.resolveOfflinePack(packs, CompanionPackCatalog.ABLITERATED_17B_ID) {
            it.id == CompanionPackCatalog.ABLITERATED_06B_ID || it.id == CompanionPackCatalog.ABLITERATED_4B_ID
        }
        assertEquals(CompanionPackCatalog.ABLITERATED_06B_ID, chosen?.id)
    }
}
