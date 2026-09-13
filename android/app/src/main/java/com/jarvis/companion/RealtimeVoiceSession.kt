package com.jarvis.companion

import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withContext
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.ArrayDeque
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * RFC-0064 duplex voice session. Auth uses the same Bearer + device headers as HTTPS —
 * never query-string tokens. Audio frames are PCM16LE @ 16 kHz, base64 in JSON.
 */
class RealtimeVoiceSession(
    private val api: JarvisApi,
    private val conversationId: String?,
    private val voiceProfileId: String?,
    private val inferenceProfile: String? = null,
) {
    private var socket: WebSocket? = null
    private val events = Channel<JSONObject>(Channel.BUFFERED)
    private val pending = ArrayDeque<JSONObject>()
    private val open = AtomicBoolean(false)
    var sessionId: String = ""
        private set
    var turnId: String = ""
        private set
    private var nextSeq = 0

    suspend fun connect() = withContext(Dispatchers.IO) {
        api.ensureSession()
        val client = api.pinnedClient().newBuilder().readTimeout(0, TimeUnit.MILLISECONDS).build()
        val url = api.preferredOrigin().replace("https://", "wss://").replace("http://", "ws://") +
            "/api/companion/voice/realtime"
        val request = Request.Builder().url(url)
            .header("Authorization", "Bearer ${api.accessToken()}")
            .header("X-Jarvis-Device", api.deviceId)
            .build()
        suspendCancellableCoroutine { cont ->
            socket = client.newWebSocket(request, object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    open.set(true)
                    if (cont.isActive) cont.resume(Unit)
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    runCatching { JSONObject(text) }.onSuccess { events.trySend(it) }
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    open.set(false)
                    events.trySend(JSONObject().put("type", "error").put("detail", t.message ?: "socket failed"))
                    if (cont.isActive) cont.resumeWithException(t)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    open.set(false)
                    events.close()
                }
            })
            cont.invokeOnCancellation { socket?.close(1000, "cancel") }
        }
        val hello = JSONObject().put("type", "hello")
        conversationId?.let { hello.put("conversation_id", it) }
        voiceProfileId?.takeIf { it.isNotEmpty() }?.let { hello.put("voice_profile_id", it) }
        inferenceProfile?.takeIf { it.isNotEmpty() && it != "auto" }?.let { hello.put("profile", it) }
        send(hello)
        val opened = awaitType("session")
        sessionId = opened.getString("session_id")
    }

    suspend fun startTurn(): String {
        send(JSONObject().put("type", "start_turn"))
        val turn = awaitType("turn")
        turnId = turn.getString("turn_id")
        nextSeq = 0
        return turnId
    }

    fun sendPcm(frame: ByteArray) {
        val body = JSONObject()
            .put("type", "audio")
            .put("turn_id", turnId)
            .put("seq", nextSeq++)
            .put("format", "pcm16le")
            .put("sample_rate", 16000)
            .put("data", Base64.encodeToString(frame, Base64.NO_WRAP))
        send(body)
    }

    fun endTurn() {
        send(JSONObject().put("type", "end_turn").put("turn_id", turnId))
    }

    fun interrupt() {
        if (turnId.isNotEmpty()) send(JSONObject().put("type", "interrupt").put("turn_id", turnId))
    }

    suspend fun nextEvent(): JSONObject {
        while (pending.isNotEmpty()) return pending.removeFirst()
        return events.receive()
    }

    fun close() {
        runCatching { send(JSONObject().put("type", "close")) }
        socket?.close(1000, "done")
        socket = null
        open.set(false)
        events.close()
    }

    private fun send(body: JSONObject) {
        check(open.get()) { "Realtime voice socket is not open" }
        check(socket?.send(body.toString()) == true) { "Failed to send voice frame" }
    }

    private suspend fun awaitType(type: String): JSONObject {
        while (true) {
            val event = if (pending.isNotEmpty()) pending.removeFirst() else events.receive()
            when (event.optString("type")) {
                "error" -> throw IllegalStateException(event.optString("detail", "Realtime voice error"))
                type -> return event
                else -> pending.addLast(event)
            }
        }
    }
}
