package com.jarvis.companion

import android.app.*
import android.content.Intent
import android.os.IBinder
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.telecom.CallAttributesCompat
import androidx.core.telecom.CallsManager
import androidx.core.telecom.CallControlScope
import androidx.core.telecom.CallEndpointCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import android.telecom.DisconnectCause
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.*
import org.json.JSONObject
import org.webrtc.*
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

private const val CALL_CHANNEL = "jarvis-calls"

data class CallUiState(val active: Boolean = false, val status: String = "", val muted: Boolean = false,
                       val route: String = "", val routes: List<Pair<String, String>> = emptyList())
object CurrentCall {
    internal val mutable = MutableStateFlow(CallUiState())
    val state = mutable.asStateFlow()
}

class JarvisPushService : FirebaseMessagingService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    override fun onNewToken(token: String) {
        scope.launch { runCatching { (application as JarvisApp).api.json("/preferences", "PUT", JSONObject().put("push_token", token)) } }
    }
    override fun onMessageReceived(message: RemoteMessage) {
        val id = message.data["event_id"] ?: return
        val kind = message.data["kind"] ?: return
        if (kind == "call") {
            // Push is a wake hint, not authority. Verify the live call before ringing.
            scope.launch {
                runCatching {
                    val call = (application as JarvisApp).api.json("/calls/$id")
                    if (call.optString("state") != "ringing") return@runCatching
                    val manager = getSystemService(NotificationManager::class.java)
                    manager.createNotificationChannel(NotificationChannel(CALL_CHANNEL, "Jarvis calls", NotificationManager.IMPORTANCE_HIGH))
                    val open = PendingIntent.getActivity(this@JarvisPushService, id.hashCode(), Intent(this@JarvisPushService, MainActivity::class.java).putExtra("incoming_call", id), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                    val decline = PendingIntent.getService(this@JarvisPushService, id.hashCode(), Intent(this@JarvisPushService, CallService::class.java).setAction("decline").putExtra("call_id", id), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                    val notification = NotificationCompat.Builder(this@JarvisPushService, CALL_CHANNEL).setSmallIcon(R.drawable.ic_jarvis)
                        .setContentTitle("Jarvis is calling").setContentText("A critical event needs your attention")
                        .setCategory(NotificationCompat.CATEGORY_CALL).setPriority(NotificationCompat.PRIORITY_MAX)
                        .setContentIntent(open).setFullScreenIntent(open, true).setTimeoutAfter(45000)
                        .addAction(0, "Open to answer", open).addAction(0, "Decline", decline).setAutoCancel(true).build()
                    manager.notify(id.hashCode(), notification)
                }
            }
        } else if (kind == "task") {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("jarvis-tasks", "Task updates", NotificationManager.IMPORTANCE_DEFAULT))
            val open = PendingIntent.getActivity(this, id.hashCode(), Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            manager.notify(id.hashCode(), NotificationCompat.Builder(this, "jarvis-tasks").setSmallIcon(R.drawable.ic_jarvis)
                .setContentTitle("Jarvis has an update").setContentText("Open Jarvis to view the task").setContentIntent(open).setAutoCancel(true).build())
        }
    }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}

class CallService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var media: RealtimeMediaClient? = null
    private var callId: String? = null
    private var starting = false
    private var control: CallControlScope? = null
    private var endpoints: List<CallEndpointCompat> = emptyList()
    private var userMuted = false
    private var systemMuted = false
    private var held = false
    private var generation = 0
    private var reconnectJob: Job? = null
    private fun applyMute() {
        media?.setMuted(userMuted || systemMuted || held)
        CurrentCall.mutable.value = CurrentCall.mutable.value.copy(muted = userMuted || systemMuted || held)
    }
    private val api get() = (application as JarvisApp).api
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "mute") {
            userMuted = !userMuted; applyMute()
            return START_NOT_STICKY
        }
        if (intent?.action == "route") {
            val endpoint = endpoints.firstOrNull { it.identifier.toString() == intent.getStringExtra("endpoint") }
            if (endpoint != null) scope.launch { control?.requestEndpointChange(endpoint) }
            return START_NOT_STICKY
        }
        if (intent?.action in listOf("end", "decline")) {
            scope.launch {
                runCatching { control?.disconnect(DisconnectCause(DisconnectCause.LOCAL)) }
                val id = intent?.getStringExtra("call_id") ?: callId
                if (id != null) {
                    getSystemService(NotificationManager::class.java).cancel(id.hashCode())
                    runCatching { api.json("/calls/$id/end", "POST") }
                }
                stopSelf()
            }
            return START_NOT_STICKY
        }
        if (callId != null || starting) return START_NOT_STICKY
        starting = true
        CurrentCall.mutable.value = CallUiState(active = true, status = "Connecting")
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CALL_CHANNEL, "Jarvis calls", NotificationManager.IMPORTANCE_HIGH))
        val hangup = PendingIntent.getService(this, 1, Intent(this, CallService::class.java).setAction("end"), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        startForeground(9, NotificationCompat.Builder(this, CALL_CHANNEL).setSmallIcon(R.drawable.ic_jarvis).setContentTitle("Calling Jarvis")
            .setContentText("Connecting encrypted audio").setOngoing(true).addAction(0, "Hang up", hangup).build())
        scope.launch {
            try {
                val incoming = intent?.getStringExtra("call_id")
                val call = if (incoming != null) api.json("/calls/$incoming") else api.json("/calls", "POST", JSONObject())
                callId = call.getString("id")
                manager.cancel(callId!!.hashCode())
                val callsManager = CallsManager(this@CallService)
                callsManager.registerAppWithTelecom(CallsManager.CAPABILITY_BASELINE)
                val attributes = CallAttributesCompat("Jarvis", Uri.parse("jarvis:swarm"), if (incoming != null) CallAttributesCompat.DIRECTION_INCOMING else CallAttributesCompat.DIRECTION_OUTGOING)
                callsManager.addCall(attributes,
                    onAnswer = { },
                    onDisconnect = { stopSelf() },
                    onSetActive = { held = false; applyMute() },
                    onSetInactive = { held = true; applyMute() }) {
                    val currentControl = this
                    control = currentControl
                    launch { currentControl.isMuted.collect { systemMuted = it; applyMute() } }
                    launch { currentControl.availableEndpoints.collect { values ->
                        endpoints = values
                        CurrentCall.mutable.value = CurrentCall.mutable.value.copy(routes = values.map { it.identifier.toString() to it.name.toString() })
                    } }
                    launch { currentControl.currentCallEndpoint.collect { CurrentCall.mutable.value = CurrentCall.mutable.value.copy(route = it.name.toString()) } }
                    scope.launch {
                        try {
                            val first = newMedia(call, currentControl)
                            media = first
                            first.connect(api, call, generation)
                            applyMute()
                            if (incoming != null) currentControl.answer(CallAttributesCompat.CALL_TYPE_AUDIO_CALL) else currentControl.setActive()
                        } catch (e: Exception) {
                            currentControl.disconnect(DisconnectCause(DisconnectCause.ERROR))
                            stopSelf()
                        }
                    }
                }
            } catch (e: Exception) {
                if (e !is CancellationException) manager.notify(10, NotificationCompat.Builder(this@CallService, CALL_CHANNEL).setSmallIcon(R.drawable.ic_jarvis).setContentTitle("Jarvis call unavailable").setContentText(e.message ?: "Continue by text").build())
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }
    private fun newMedia(call: JSONObject, callControl: CallControlScope): RealtimeMediaClient {
        lateinit var candidate: RealtimeMediaClient
        candidate = RealtimeMediaClient(this) { connected ->
            scope.launch {
                if (candidate !== media) return@launch
                if (connected) CurrentCall.mutable.value = CurrentCall.mutable.value.copy(status = "Encrypted call")
                else reconnect(call, callControl, candidate)
            }
        }
        return candidate
    }
    private fun reconnect(call: JSONObject, callControl: CallControlScope, failed: RealtimeMediaClient) {
        if (reconnectJob?.isActive == true || failed !== media) return
        CurrentCall.mutable.value = CurrentCall.mutable.value.copy(status = "Reconnecting encrypted audio")
        reconnectJob = scope.launch {
            media = null
            failed.close()
            repeat(3) { attempt ->
                delay((1L shl attempt) * 1000)
                generation += 1
                val candidate = newMedia(call, callControl)
                media = candidate
                try {
                    candidate.connect(api, call, generation)
                    applyMute()
                    return@launch
                } catch (_: Exception) {
                    if (media === candidate) media = null
                    candidate.close()
                }
            }
            CurrentCall.mutable.value = CurrentCall.mutable.value.copy(status = "Call connection lost")
            runCatching { callControl.disconnect(DisconnectCause(DisconnectCause.ERROR)) }
            stopSelf()
        }
    }
    override fun onDestroy() {
        CurrentCall.mutable.value = CallUiState()
        media?.close(); scope.cancel()
        callId?.let { id -> CoroutineScope(Dispatchers.IO).launch { runCatching { api.json("/calls/$id/end", "POST") } } }
        super.onDestroy()
    }
}

class RealtimeMediaClient(context: android.content.Context, private val connection: (Boolean) -> Unit) {
    private val factory: PeerConnectionFactory
    private var peer: PeerConnection? = null
    private var source: AudioSource? = null
    private var track: AudioTrack? = null
    init {
        PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(context).createInitializationOptions())
        factory = PeerConnectionFactory.builder().createPeerConnectionFactory()
    }
    suspend fun connect(api: JarvisApi, call: JSONObject, generation: Int) {
        val servers = call.optJSONArray("ice_servers")?.objects()?.map { server ->
            val urls = server.getJSONArray("urls")
            PeerConnection.IceServer.builder((0 until urls.length()).map(urls::getString)).setUsername(server.optString("username")).setPassword(server.optString("credential")).createIceServer()
        } ?: emptyList()
        val gathered = CompletableDeferred<Unit>()
        peer = factory.createPeerConnection(PeerConnection.RTCConfiguration(servers), object : PeerConnection.Observer {
            override fun onSignalingChange(state: PeerConnection.SignalingState) {}
            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                if (state == PeerConnection.IceConnectionState.CONNECTED || state == PeerConnection.IceConnectionState.COMPLETED) connection(true)
                if (state == PeerConnection.IceConnectionState.FAILED) connection(false)
            }
            override fun onIceConnectionReceivingChange(receiving: Boolean) {}
            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) { if (state == PeerConnection.IceGatheringState.COMPLETE) gathered.complete(Unit) }
            override fun onIceCandidate(candidate: IceCandidate) {}
            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) {}
            override fun onAddStream(stream: MediaStream) {}
            override fun onRemoveStream(stream: MediaStream) {}
            override fun onDataChannel(channel: DataChannel) {}
            override fun onRenegotiationNeeded() {}
            override fun onAddTrack(receiver: RtpReceiver, streams: Array<out MediaStream>) {}
        }) ?: error("WebRTC could not initialize")
        source = factory.createAudioSource(MediaConstraints())
        track = factory.createAudioTrack("microphone", source)
        peer!!.addTrack(track)
        val offer = suspendCancellableCoroutine<SessionDescription> { continuation -> peer!!.createOffer(object : SdpObserver {
            override fun onCreateSuccess(description: SessionDescription) { continuation.resume(description) }
            override fun onCreateFailure(error: String) { continuation.resumeWithException(IllegalStateException(error)) }
            override fun onSetSuccess() {}
            override fun onSetFailure(error: String) {}
        }, MediaConstraints()) }
        setDescription(offer, true)
        withTimeout(20000) { gathered.await() }
        val response = api.json("/calls/${call.getString("id")}/offer", "POST", JSONObject().put("type", "offer")
            .put("generation", generation).put("sdp", peer!!.localDescription.description))
        setDescription(SessionDescription(SessionDescription.Type.ANSWER, response.getString("sdp")), false)
    }
    private suspend fun setDescription(description: SessionDescription, local: Boolean) = suspendCancellableCoroutine<Unit> { continuation ->
        val observer = object : SdpObserver {
            override fun onSetSuccess() { continuation.resume(Unit) }
            override fun onSetFailure(error: String) { continuation.resumeWithException(IllegalStateException(error)) }
            override fun onCreateSuccess(description: SessionDescription) {}
            override fun onCreateFailure(error: String) {}
        }
        if (local) peer!!.setLocalDescription(observer, description) else peer!!.setRemoteDescription(observer, description)
    }
    fun setMuted(muted: Boolean) { track?.setEnabled(!muted) }
    fun close() { peer?.close(); peer?.dispose(); track?.dispose(); source?.dispose(); factory.dispose() }
}
