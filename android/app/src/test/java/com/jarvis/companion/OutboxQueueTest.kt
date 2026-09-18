package com.jarvis.companion

import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class OutboxQueueTest {
    @Test
    fun queuePersistsAndMarksSynced() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val queue = OutboxQueue(context)
        queue.clear()
        val id = "11111111-1111-1111-1111-111111111111"
        queue.append(
            JSONObject()
                .put("request_id", id)
                .put("client_message_id", id)
                .put("role", "user")
                .put("text", "offline ping")
                .put("origin", "device_offline"),
        )
        assertEquals(1, queue.pendingCount())
        queue.markSynced(listOf(id))
        queue.pruneSynced()
        assertEquals(0, queue.pendingCount())
    }
}
