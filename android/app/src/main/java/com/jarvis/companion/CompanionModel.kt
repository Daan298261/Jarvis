package com.jarvis.companion

import android.Manifest
import android.app.Application
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.media.MediaRecorder.AudioSource
import android.net.Uri
import android.content.ContentProviderOperation
import android.content.Intent
import android.provider.ContactsContract
import android.util.Base64
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.LinkedBlockingQueue

data class CompanionState(
    val connected: Boolean = false, val activity: String = "Offline", val error: String? = null,
    val busy: Boolean = false, val recording: Boolean = false, val speaking: Boolean = false, val pendingMessage: Boolean = false,
    val tasks: List<JSONObject> = emptyList(), val models: List<JSONObject> = emptyList(),
    val messages: List<JSONObject> = emptyList(), val conversations: List<JSONObject> = emptyList(),
    val schedules: List<JSONObject> = emptyList(), val calls: List<JSONObject> = emptyList(),
    val conversationId: String? = null, val selectedModel: String = "auto",
    val attachmentIds: List<String> = emptyList(),
    val attachmentUploadProgress: Int = 0,
    val attachmentUploadBusy: Boolean = false,
    val capabilities: JSONObject = JSONObject(),
    val swarm: JSONObject = JSONObject(), val coding: JSONObject = JSONObject(),
    val codingDecisions: List<JSONObject> = emptyList(), val voiceProfiles: List<JSONObject> = emptyList(),
    val selectedVoice: String = "", val presenceMode: String = "orb",
    val liveTranscript: String = "", val voiceMode: String = "clip",
    val inferenceLoaded: Boolean = false, val inferenceLoading: Boolean = false,
    val inferenceProfile: String = "", val inferenceFamily: String = "", val inferenceError: String = "",
    val leaderReachable: Boolean = false,
    val localPackStatus: String = "missing",
    val localPackProgress: Int = 0,
    val localPackError: String = "",
    val voiceSttStatus: String = "missing",
    val voiceTtsStatus: String = "missing",
    val voicePackProgress: Int = 0,
    val voicePackError: String = "",
    val onDeviceVoiceActive: Boolean = false,
    val voiceRouteBanner: String? = null,
    val offlineQueueDepth: Int = 0,
    val offlineAnswering: Boolean = false,
    val lanStatus: String = "idle",
    val lanLabel: String = "",
    val pendingApproval: Boolean = false,
)

fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }

private data class RefreshPayload(
    val capabilities: JSONObject,
    val tasks: List<JSONObject>,
    val models: List<JSONObject>,
    val inference: JSONObject,
    val conversations: List<JSONObject>,
    val schedules: List<JSONObject>,
    val calls: List<JSONObject>,
    val messages: List<JSONObject>,
    val swarm: JSONObject,
    val coding: JSONObject,
    val voices: JSONObject,
)

class CompanionModel(app: Application) : AndroidViewModel(app) {
    private val jarvisApp = app as JarvisApp
    val api = jarvisApp.api
    private val deviceModelChrome = jarvisApp.deviceModelChrome
    private val companionPrefs = app.getSharedPreferences("companion_ui", Application.MODE_PRIVATE)
    private val mutable = MutableStateFlow(CompanionState(
        selectedModel = companionPrefs.getString("inference_profile", "auto") ?: "auto",
        selectedVoice = companionPrefs.getString("voice_profile", "") ?: "",
        presenceMode = companionPrefs.getString("presence_mode", "orb").takeIf { it in setOf("orb", "humanoid") } ?: "orb",
    ))
    val state = mutable.asStateFlow()
    private var recorder: MediaRecorder? = null
    private var recordingFile: File? = null
    private var player: MediaPlayer? = null
    private var playerFile: File? = null
    private val outbox = Outbox(app)
    private val uploadOutbox = UploadOutbox(app)
    private val offlineQueue = OutboxQueue(app)
    val packManager = CompanionPackManager(app)
    val voicePackManager = CompanionVoicePackManager(app)
    private var foreground = false
    private val sendLock = kotlinx.coroutines.sync.Mutex()
    private var audioRecord: AudioRecord? = null
    private var realtime: RealtimeVoiceSession? = null
    private var captureJob: Job? = null
    private var listenJob: Job? = null
    private val ttsQueue = LinkedBlockingQueue<ByteArray>()
    private var ttsJob: Job? = null
    private var onDevicePcm: java.io.ByteArrayOutputStream? = null
    private var onDeviceListening = false
    init {
        deviceModelChrome.actions = object : DevicePackChromeActions {
            override fun downloadSelectedPack() {
                downloadCompanionPack()
            }
            override fun deleteSelectedPack() {
                deleteCompanionPack()
            }
            override fun selectPack(packId: String) {
                selectCompanionPack(packId)
            }
        }
        viewModelScope.launch {
            state.collect { companionState ->
                DevicePackChromePublisher.publish(this@CompanionModel, deviceModelChrome, companionState)
            }
        }
        runCatching { outbox.read() }.onSuccess { mutable.value = mutable.value.copy(pendingMessage = it != null) }
            .onFailure { mutable.value = mutable.value.copy(error = "Cannot recover pending message: ${it.message}") }
        viewModelScope.launch {
            runCatching { packManager.refreshStatus() }
            runCatching { voicePackManager.refreshStatus() }
            mutable.value = mutable.value.copy(
                localPackStatus = packManager.status(),
                localPackProgress = packManager.downloadProgress(),
                localPackError = packManager.lastError(),
                voiceSttStatus = voicePackManager.sttStatus(),
                voiceTtsStatus = voicePackManager.ttsStatus(),
                voicePackProgress = voicePackManager.downloadProgress(),
                voicePackError = voicePackManager.lastError(),
                offlineQueueDepth = offlineQueue.pendingCount(),
            )
            publishVoiceRoute()
        }
        viewModelScope.launch {
            while (true) {
                if (foreground && api.deviceId.isNotEmpty()) {
                    if (mutable.value.pendingApproval) {
                        runCatching {
                            api.session()
                            refresh()
                            mutable.value = mutable.value.copy(pendingApproval = false, lanStatus = "idle", lanLabel = "")
                        }
                    } else {
                        runCatching { refresh() }.onFailure {
                            mutable.value = mutable.value.copy(
                                connected = false,
                                leaderReachable = false,
                                activity = "Offline",
                                error = it.message,
                            )
                        }
                    }
                }
                delay(4000)
            }
        }
        if (api.deviceId.isEmpty()) startLanScan()
    }

    fun startLanScan() {
        if (api.deviceId.isNotEmpty()) return
        viewModelScope.launch {
            mutable.value = mutable.value.copy(lanStatus = "scanning", lanLabel = "Scanning this Wi‑Fi for Jarvis…", error = null)
            var host = runCatching { LanScanner.scan() }.getOrNull()
            if (host == null) {
                delay(900)
                host = runCatching { LanScanner.scan(timeoutMs = 4000) }.getOrNull()
            }
            if (host == null) {
                mutable.value = mutable.value.copy(
                    lanStatus = "idle",
                    lanLabel = "",
                    error = "No Jarvis desktop found on this Wi-Fi. On the PC open Settings → Phone Pairing and tap Prepare connection, then try again.",
                )
                return@launch
            }
            mutable.value = mutable.value.copy(
                lanStatus = "requesting",
                lanLabel = "Found ${host.name} — asking your PC to approve this phone",
            )
            try {
                api.configure(host.endpoint, host.serverPin)
                api.lanEnroll()
                try {
                    api.session()
                    jarvisApp.registerPush()
                    refresh()
                    mutable.value = mutable.value.copy(pendingApproval = false, lanStatus = "idle", lanLabel = "")
                } catch (error: ApiException) {
                    if (error.status != 403) throw error
                    mutable.value = mutable.value.copy(
                        pendingApproval = true,
                        lanStatus = "waiting",
                        lanLabel = "Waiting for approval on your Jarvis PC",
                        activity = "Confirm this phone on the desktop",
                    )
                }
            } catch (error: kotlinx.coroutines.CancellationException) {
                throw error
            } catch (error: Exception) {
                mutable.value = mutable.value.copy(
                    lanStatus = "failed",
                    lanLabel = "Found Jarvis but could not request pairing",
                    error = error.message,
                )
            }
        }
    }
    fun setForeground(value: Boolean) { foreground = value }
    fun action(block: suspend () -> Unit) = viewModelScope.launch {
        mutable.value = mutable.value.copy(busy = true, error = null)
        try { block() } catch (e: kotlinx.coroutines.CancellationException) { throw e }
        catch (e: Exception) { mutable.value = mutable.value.copy(error = e.message) }
        finally { mutable.value = mutable.value.copy(busy = false) }
    }
    fun offlineStatusJson(): JSONObject = CompanionOfflineHooks.statusSnapshot(this)

    fun refreshCompanionPackStatus() = action {
        packManager.refreshStatus()
        mutable.value = mutable.value.copy(
            localPackStatus = packManager.status(),
            localPackProgress = packManager.downloadProgress(),
            localPackError = packManager.lastError(),
            offlineQueueDepth = offlineQueue.pendingCount(),
        )
    }

    fun downloadCompanionPack() = action {
        packManager.downloadSelected { progress ->
            mutable.value = mutable.value.copy(localPackProgress = progress, localPackStatus = CompanionPackStatus.DOWNLOADING)
        }
        mutable.value = mutable.value.copy(
            localPackStatus = packManager.status(),
            localPackError = packManager.lastError(),
            localPackProgress = packManager.downloadProgress(),
        )
    }

    fun deleteCompanionPack() = action {
        packManager.deleteSelected()
        mutable.value = mutable.value.copy(
            localPackStatus = packManager.status(),
            localPackProgress = 0,
            localPackError = "",
        )
    }

    fun selectCompanionPack(id: String) {
        packManager.selectPack(id)
    }

    fun refreshVoicePackStatus() = action {
        voicePackManager.refreshStatus()
        mutable.value = mutable.value.copy(
            voiceSttStatus = voicePackManager.sttStatus(),
            voiceTtsStatus = voicePackManager.ttsStatus(),
            voicePackProgress = voicePackManager.downloadProgress(),
            voicePackError = voicePackManager.lastError(),
        )
        publishVoiceRoute()
    }

    fun downloadVoicePack(packId: String) = action {
        voicePackManager.downloadPack(packId) { progress ->
            mutable.value = mutable.value.copy(voicePackProgress = progress)
        }
        mutable.value = mutable.value.copy(
            voiceSttStatus = voicePackManager.sttStatus(),
            voiceTtsStatus = voicePackManager.ttsStatus(),
            voicePackProgress = voicePackManager.downloadProgress(),
            voicePackError = voicePackManager.lastError(),
        )
        publishVoiceRoute()
    }

    fun downloadRecommendedVoicePacks() = action {
        voicePackManager.downloadRecommendedPair { progress ->
            mutable.value = mutable.value.copy(voicePackProgress = progress)
        }
        mutable.value = mutable.value.copy(
            voiceSttStatus = voicePackManager.sttStatus(),
            voiceTtsStatus = voicePackManager.ttsStatus(),
            voicePackProgress = voicePackManager.downloadProgress(),
            voicePackError = voicePackManager.lastError(),
        )
        publishVoiceRoute()
    }

    fun deleteVoicePack(packId: String) = action {
        voicePackManager.deletePack(packId)
        mutable.value = mutable.value.copy(
            voiceSttStatus = voicePackManager.sttStatus(),
            voiceTtsStatus = voicePackManager.ttsStatus(),
            voicePackProgress = 0,
            voicePackError = voicePackManager.lastError(),
        )
        publishVoiceRoute()
    }

    fun selectSttVoicePack(id: String) {
        voicePackManager.selectSttPack(id)
        viewModelScope.launch {
            voicePackManager.refreshStatus()
            mutable.value = mutable.value.copy(voiceSttStatus = voicePackManager.sttStatus())
            publishVoiceRoute()
        }
    }

    fun selectTtsVoicePack(id: String) {
        voicePackManager.selectTtsPack(id)
        viewModelScope.launch {
            voicePackManager.refreshStatus()
            mutable.value = mutable.value.copy(voiceTtsStatus = voicePackManager.ttsStatus())
            publishVoiceRoute()
        }
    }

    private fun publishVoiceRoute() {
        val state = mutable.value
        val voiceCaps = state.capabilities.optJSONObject("voice")
        val decision = CompanionVoiceRouting.decide(
            leaderReachable = state.leaderReachable || state.connected,
            realtimeVoiceHealthy = state.connected && voiceCaps?.optBoolean("realtime") == true,
            hostTtsHealthy = state.connected && voiceCaps?.optBoolean("tts_ready") == true,
            sttPackStatus = voicePackManager.sttStatus(),
            ttsPackStatus = voicePackManager.ttsStatus(),
            localLlmReady = packManager.isPackReady(),
        )
        mutable.value = state.copy(
            onDeviceVoiceActive = decision.onDeviceIndicator,
            voiceRouteBanner = decision.banner ?: decision.error,
            voiceSttStatus = voicePackManager.sttStatus(),
            voiceTtsStatus = voicePackManager.ttsStatus(),
        )
    }

    suspend fun refresh() {
        api.refreshEndpoints()
        val previous = mutable.value
        val previousCoding = JSONObject().put("overview", previous.coding)
            .put("decisions", JSONObject().put("items", JSONArray(previous.codingDecisions)))
        val previousVoices = JSONObject().put("active_voice_profile_id", previous.selectedVoice)
            .put("profiles", JSONArray(previous.voiceProfiles))
        val payload = kotlinx.coroutines.coroutineScope {
            val capabilities = async { api.json("/capabilities") }
            val tasks = async { api.array("/tasks").objects() }
            val modelsBody = async { api.json("/models") }
            val packCatalog = async { runCatching { api.json("/model-packs") }.getOrNull() }
            val voiceCatalog = async { runCatching { api.json("/voice-packs") }.getOrNull() }
            val conversations = async { api.array("/conversations").objects() }
            val schedules = async { api.array("/schedules").objects() }
            val calls = async { api.array("/calls").objects() }
            val messages = async {
                previous.conversationId?.let { api.json("/conversations/$it").getJSONArray("messages").objects() } ?: emptyList()
            }
            val swarm = async { runCatching { api.json("/swarm") }.getOrDefault(previous.swarm) }
            val coding = async { runCatching { api.json("/coding") }.getOrDefault(previousCoding) }
            val voices = async { runCatching { api.json("/voice/profiles") }.getOrDefault(previousVoices) }
            val modelsJson = modelsBody.await()
            packCatalog.await()?.let { packManager.updateCatalog(it) }
            voiceCatalog.await()?.let { voicePackManager.updateCatalog(it) }
            runCatching { packManager.refreshStatus() }
            runCatching { voicePackManager.refreshStatus() }
            RefreshPayload(
                capabilities.await(),
                tasks.await(),
                modelsJson.optJSONArray("models")?.objects() ?: emptyList(),
                modelsJson.optJSONObject("inference") ?: JSONObject(),
                conversations.await(),
                schedules.await(),
                calls.await(),
                messages.await(),
                swarm.await(),
                coding.await(),
                voices.await(),
            )
        }
        val active = payload.tasks.firstOrNull { it.optString("status") in listOf("queued", "running", "waiting") }
        val voiceProfiles = payload.voices.optJSONArray("profiles")?.objects() ?: emptyList()
        val selectedVoice = previous.selectedVoice.takeIf { selected ->
            voiceProfiles.any { it.optString("id") == selected && it.optBoolean("available") }
        } ?: payload.voices.optString("active_voice_profile_id").takeIf { activeVoice ->
            voiceProfiles.any { it.optString("id") == activeVoice && it.optBoolean("available") }
        } ?: voiceProfiles.firstOrNull { it.optBoolean("available") }?.optString("id").orEmpty()
        val selectedModel = previous.selectedModel.takeIf { selected ->
            selected == "auto" || payload.models.any { it.optString("name") == selected && it.optBoolean("installed") }
        } ?: "auto"
        val inference = payload.inference
        val inferenceProfile = inference.optString("profile")
        val inferenceLabel = payload.models.firstOrNull { it.optString("name") == inferenceProfile }?.optString("label")
            ?: inference.optString("family").ifBlank { inferenceProfile }
        val wasOffline = !previous.leaderReachable
        mutable.value = mutable.value.copy(
            connected = true,
            leaderReachable = true,
            activity = active?.optString("activity") ?: "Ready when you are",
            tasks = payload.tasks,
            models = payload.models,
            conversations = payload.conversations,
            schedules = payload.schedules,
            calls = payload.calls,
            messages = payload.messages,
            capabilities = payload.capabilities,
            swarm = payload.swarm,
            coding = payload.coding.optJSONObject("overview") ?: JSONObject(),
            codingDecisions = payload.coding.optJSONObject("decisions")?.optJSONArray("items")?.objects() ?: emptyList(),
            voiceProfiles = voiceProfiles,
            selectedVoice = selectedVoice,
            selectedModel = selectedModel,
            inferenceLoaded = inference.optBoolean("loaded"),
            inferenceLoading = inference.optBoolean("loading"),
            inferenceProfile = inferenceProfile,
            inferenceFamily = inferenceLabel,
            inferenceError = inference.optString("last_error"),
            pendingMessage = outbox.read() != null,
            localPackStatus = packManager.status(),
            localPackProgress = packManager.downloadProgress(),
            localPackError = packManager.lastError(),
            voiceSttStatus = voicePackManager.sttStatus(),
            voiceTtsStatus = voicePackManager.ttsStatus(),
            voicePackProgress = voicePackManager.downloadProgress(),
            voicePackError = voicePackManager.lastError(),
            offlineQueueDepth = offlineQueue.pendingCount(),
        )
        publishVoiceRoute()
        if (CompanionRouting.shouldSyncAfterLeaderReturn(wasOffline, true, offlineQueue.pendingCount())) {
            syncOfflineTurns()
        }
        cacheConversationSnapshot(payload.messages)
    }
    fun pair(endpoint: String, pin: String, credential: String, candidates: List<String> = emptyList()) = action {
        api.configure(endpoint, pin, candidates)
        if (api.deviceId.isEmpty()) api.pair(credential.trim())
        try {
            api.session()
        } catch (error: ApiException) {
            if (error.status != 403) throw error
            mutable.value = mutable.value.copy(
                connected = false,
                pendingApproval = true,
                lanStatus = "waiting",
                lanLabel = "Waiting for approval on your Jarvis PC",
                activity = "Confirm this phone on the desktop",
                error = null,
            )
            return@action
        }
        (getApplication<Application>() as JarvisApp).registerPush()
        mutable.value = mutable.value.copy(pendingApproval = false, lanStatus = "idle", lanLabel = "")
        refresh()
    }

    suspend fun fetchStudioStatus(): JSONObject {
        if (api.deviceId.isNotEmpty()) {
            return runCatching { api.json("/studio") }.getOrElse { error ->
                val fallback = mutable.value.capabilities.optJSONObject("studio")
                if (fallback != null && fallback.length() > 0) fallback else throw error
            }
        }
        val fallback = mutable.value.capabilities.optJSONObject("studio")
        if (fallback != null && fallback.length() > 0) return fallback
        throw IllegalStateException("Connect to Jarvis to check BlackGrid Studio status.")
    }
    fun selectModel(value: String) {
        val allowed = value == "auto" || mutable.value.models.any { it.optString("name") == value && it.optBoolean("installed") }
        if (!allowed) return
        companionPrefs.edit().putString("inference_profile", value).apply()
        mutable.value = mutable.value.copy(selectedModel = value)
    }
    fun selectVoice(value: String) {
        if (mutable.value.voiceProfiles.none { it.optString("id") == value && it.optBoolean("available") }) return
        companionPrefs.edit().putString("voice_profile", value).apply()
        mutable.value = mutable.value.copy(selectedVoice = value)
    }
    fun selectPresence(value: String) {
        if (value !in setOf("orb", "humanoid")) return
        companionPrefs.edit().putString("presence_mode", value).apply()
        mutable.value = mutable.value.copy(presenceMode = value)
    }
    fun openConversation(id: String?) = action {
        mutable.value = mutable.value.copy(conversationId = id, messages = emptyList())
        refresh()
    }
    fun send(text: String) = action { sendNow(text) }
    private suspend fun sendNow(text: String) {
        if (text.isBlank()) return
        sendLock.lock()
        try {
        val state = mutable.value
        val routing = CompanionRouting.decide(
            leaderReachable = state.leaderReachable,
            packStatus = state.localPackStatus,
            resourceBlocked = DeviceInferenceGuard.blockReason(getApplication(), packManager.selectedPack() ?: CompanionPackCatalog.builtIn.first()),
            hasStalePendingOnlineOutbox = state.pendingMessage,
        )
        when (routing.mode) {
            RoutingMode.LEADER_ORCHESTRATED -> {
                check(outbox.read() == null) { "Resolve the pending message before sending another" }
                val content = JSONObject().put("text", text).put("profile", state.selectedModel)
                    .put("attachments", JSONArray(state.attachmentIds))
                state.conversationId?.let { content.put("conversation_id", it) }
                content.put("request_id", UUID.randomUUID().toString())
                outbox.save(JSONObject().put("device", api.deviceId).put("pin", api.pin).put("body", content))
                mutable.value = mutable.value.copy(pendingMessage = true)
                deliverPending()
            }
            RoutingMode.DEVICE_OFFLINE -> sendOffline(text)
            RoutingMode.DEVICE_BLOCKED -> error(routing.reason)
        }
        } finally { sendLock.unlock() }
    }

    private suspend fun sendOffline(text: String) {
        val userId = UUID.randomUUID().toString()
        val assistantId = UUID.randomUUID().toString()
        val userMessage = JSONObject()
            .put("id", userId)
            .put("role", "user")
            .put("text", text)
            .put("origin", "device_offline")
        val prior = mutable.value.messages + userMessage
        mutable.value = mutable.value.copy(messages = prior, offlineAnswering = true, activity = "Thinking on-device…")
        val prompt = buildOfflinePrompt(prior, text)
        val assistantText = StringBuilder()
        packManager.generate(prompt, 256) { chunk -> assistantText.append(chunk) }
        val reply = assistantText.toString().ifBlank { error("On-device model returned no tokens") }
        val assistantMessage = JSONObject()
            .put("id", assistantId)
            .put("role", "assistant")
            .put("text", reply)
            .put("origin", "device_local_draft")
        offlineQueue.append(
            JSONObject()
                .put("request_id", userId)
                .put("client_message_id", userId)
                .put("role", "user")
                .put("text", text)
                .put("origin", "device_offline"),
        )
        offlineQueue.append(
            JSONObject()
                .put("request_id", assistantId)
                .put("client_message_id", assistantId)
                .put("role", "assistant")
                .put("text", reply)
                .put("origin", "device_local_draft"),
        )
        mutable.value = mutable.value.copy(
            messages = prior + assistantMessage,
            offlineAnswering = false,
            offlineQueueDepth = offlineQueue.pendingCount(),
            activity = "Answering on-device",
            localPackStatus = packManager.status(),
        )
        packManager.unload()
    }

    private fun buildOfflinePrompt(history: List<JSONObject>, latest: String): String {
        val lines = history.takeLast(12).map { "${it.optString("role")}: ${it.optString("text")}" }
        val context = if (lines.isEmpty()) "" else lines.joinToString("\n") + "\n"
        return """
            You are Jarvis on a phone while the Windows Leader is unreachable.
            Answer briefly using only the conversation below and general knowledge.
            Do not claim to run tools, HexStrike, filesystem access, or swarm workers.
            $context
            user: $latest
            assistant:
        """.trimIndent()
    }

    private suspend fun syncOfflineTurns() {
        val pending = offlineQueue.readAll().filter { !it.optBoolean("synced", false) }
        if (pending.isEmpty()) return
        val turns = JSONArray()
        pending.forEach { turns.put(it) }
        val body = JSONObject().put("turns", turns)
        mutable.value.conversationId?.let { body.put("conversation_id", it) }
        // conversation_id optional on first offline session
        val result = api.json("/sync/offline-turns", "POST", body)
        val syncedIds = pending.map { it.optString("client_message_id").ifBlank { it.optString("request_id") } }
        offlineQueue.markSynced(syncedIds)
        offlineQueue.pruneSynced()
        mutable.value = mutable.value.copy(
            conversationId = result.optString("conversation_id", mutable.value.conversationId),
            offlineQueueDepth = offlineQueue.pendingCount(),
        )
    }

    private fun cacheConversationSnapshot(messages: List<JSONObject>) {
        if (messages.isEmpty()) return
        val array = JSONArray()
        messages.takeLast(40).forEach { array.put(it) }
        companionPrefs.edit().putString("last_synced_messages", array.toString()).apply()
    }
    fun retryPending() = action {
        sendLock.lock()
        try { deliverPending() } finally { sendLock.unlock() }
    }
    fun dismissPending() = action {
        sendLock.lock()
        try { outbox.clear(); mutable.value = mutable.value.copy(pendingMessage = false) } finally { sendLock.unlock() }
    }
    private suspend fun deliverPending() {
        val pending = outbox.read() ?: return
        check(pending.getString("device") == api.deviceId && pending.getString("pin") == api.pin) { "This pending message belongs to a different pairing" }
        val result = api.json("/messages", "POST", pending.getJSONObject("body"))
        outbox.clear()
        mutable.value = mutable.value.copy(conversationId = result.getString("conversation_id"), attachmentIds = emptyList())
        refresh()
    }
    fun upload(uri: Uri) = action { uploadNow(uri) }
    fun uploadCaptured(uri: Uri, file: File) = action {
        try { uploadNow(uri) } finally { file.delete() }
    }
    fun retryUpload() = action { resumePendingUpload() }

    private suspend fun resumePendingUpload() {
        val pending = uploadOutbox.read() ?: return
        val uri = Uri.parse(pending.getString("uri"))
        uploadNow(uri, pending.optString("upload_id").ifBlank { null })
    }

    private suspend fun uploadNow(uri: Uri, resumeUploadId: String? = null) {
        val context = getApplication<Application>()
        val name = uri.lastPathSegment ?: "attachment"
        val type = context.contentResolver.getType(uri) ?: "application/octet-stream"
        val kind = MediaUploadPlanner.detectKind(type, name)
        val size = context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
        mutable.value = mutable.value.copy(attachmentUploadBusy = true, attachmentUploadProgress = 0, error = null)
        try {
            val uploadId = resumeUploadId ?: UUID.randomUUID().toString()
            if (MediaUploadPlanner.shouldChunk(kind, size)) {
                uploadOutbox.save(
                    JSONObject()
                        .put("uri", uri.toString())
                        .put("upload_id", uploadId)
                        .put("kind", kind)
                        .put("name", name),
                )
                val bytes = withContext(Dispatchers.IO) {
                    context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                        ?: error("Cannot read attachment")
                }
                val total = MediaUploadPlanner.chunkCount(bytes.size.toLong())
                for (index in 0 until total) {
                    val start = index * MediaUploadPlanner.CHUNK_SIZE
                    val end = minOf(start + MediaUploadPlanner.CHUNK_SIZE, bytes.size)
                    val chunk = bytes.copyOfRange(start, end)
                    val headers = mapOf(
                        "X-Jarvis-Upload-Id" to uploadId,
                        "X-Jarvis-Chunk-Index" to index.toString(),
                        "X-Jarvis-Chunk-Total" to total.toString(),
                        "X-Jarvis-Upload-Kind" to kind,
                    )
                    val response = JSONObject(
                        api.raw(
                            "/attachments",
                            "POST",
                            chunk,
                            contentType = type,
                            filename = name,
                            extraHeaders = headers,
                        ).toString(Charsets.UTF_8),
                    )
                    val received = response.optInt("received", index + 1)
                    mutable.value = mutable.value.copy(
                        attachmentUploadProgress = ((received.toDouble() / total.toDouble()) * 100).toInt(),
                    )
                    if (response.has("id")) {
                        uploadOutbox.clear()
                        mutable.value = mutable.value.copy(
                            attachmentIds = mutable.value.attachmentIds + response.getString("id"),
                            attachmentUploadBusy = false,
                            attachmentUploadProgress = 100,
                        )
                        return
                    }
                }
            } else {
                val bytes = withContext(Dispatchers.IO) {
                    context.contentResolver.openInputStream(uri)?.use { stream -> stream.readBytes() }
                        ?: error("Cannot read attachment")
                }
                val headers = mapOf("X-Jarvis-Upload-Kind" to kind)
                val result = JSONObject(
                    api.raw("/attachments", "POST", bytes, contentType = type, filename = name, extraHeaders = headers)
                        .toString(Charsets.UTF_8),
                )
                uploadOutbox.clear()
                mutable.value = mutable.value.copy(
                    attachmentIds = mutable.value.attachmentIds + result.getString("id"),
                    attachmentUploadBusy = false,
                    attachmentUploadProgress = 100,
                )
            }
        } catch (error: Exception) {
            mutable.value = mutable.value.copy(
                attachmentUploadBusy = false,
                error = error.message ?: "Upload failed",
            )
            throw error
        }
    }
    fun cancel(taskId: String) = action { api.json("/tasks/$taskId/cancel", "POST"); refresh() }
    fun approve(taskId: String, token: String, approved: Boolean) = action {
        api.json("/tasks/$taskId/approve", "POST", JSONObject().put("token", token).put("approved", approved)); refresh()
    }
    fun resolveCodingDecision(itemId: String, resolution: String) = action {
        api.json("/coding/decisions/$itemId/resolve", "POST", JSONObject().put("resolution", resolution)); refresh()
    }
    fun schedule(id: String?, prompt: String, instant: java.time.ZonedDateTime, recurrence: String) = action {
        api.json(if (id == null) "/schedules" else "/schedules/$id", if (id == null) "POST" else "PUT",
            JSONObject().put("prompt", prompt).put("next_run", instant.toEpochSecond()).put("timezone", instant.zone.id)
            .put("recurrence", recurrence).put("profile", mutable.value.selectedModel))
        refresh()
    }
    fun pauseSchedule(id: String) = action { api.json("/schedules/$id/pause", "POST"); refresh() }
    fun resumeSchedule(id: String) = action { api.json("/schedules/$id/resume", "POST"); refresh() }

    fun addJarvisWhatsAppContact() = action {
        val contact = api.json("/whatsapp/contact")
        if (!contact.optBoolean("available", false)) {
            error(contact.optString("reason", "WhatsApp contact is unavailable"))
        }
        val display = contact.optString("display_name", "Jarvis")
        val phone = contact.optString("phone_e164").ifBlank { "+${contact.optString("phone_digits")}" }
        val note = contact.optString("note")
        val ops = ArrayList<ContentProviderOperation>()
        ops += ContentProviderOperation.newInsert(ContactsContract.RawContacts.CONTENT_URI)
            .withValue(ContactsContract.RawContacts.ACCOUNT_TYPE, null)
            .withValue(ContactsContract.RawContacts.ACCOUNT_NAME, null)
            .build()
        ops += ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI)
            .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
            .withValue(ContactsContract.Data.MIMETYPE, ContactsContract.CommonDataKinds.StructuredName.CONTENT_ITEM_TYPE)
            .withValue(ContactsContract.CommonDataKinds.StructuredName.DISPLAY_NAME, display)
            .build()
        ops += ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI)
            .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
            .withValue(ContactsContract.Data.MIMETYPE, ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE)
            .withValue(ContactsContract.CommonDataKinds.Phone.NUMBER, phone)
            .withValue(ContactsContract.CommonDataKinds.Phone.TYPE, ContactsContract.CommonDataKinds.Phone.TYPE_MOBILE)
            .build()
        if (note.isNotBlank()) {
            ops += ContentProviderOperation.newInsert(ContactsContract.Data.CONTENT_URI)
                .withValueBackReference(ContactsContract.Data.RAW_CONTACT_ID, 0)
                .withValue(ContactsContract.Data.MIMETYPE, ContactsContract.CommonDataKinds.Note.CONTENT_ITEM_TYPE)
                .withValue(ContactsContract.CommonDataKinds.Note.NOTE, note)
                .build()
        }
        getApplication<Application>().contentResolver.applyBatch(ContactsContract.AUTHORITY, ops)
        val waMe = contact.optString("wa_me_url")
        if (waMe.isNotBlank()) {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(waMe)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            getApplication<Application>().startActivity(intent)
        }
    }

    fun preferences(notifications: Boolean, calls: Boolean) = action {
        api.json("/preferences", "PUT", JSONObject().put("notifications", notifications).put("critical_calls", calls))
        refresh()
    }
    fun toggleRecord() {
        val voiceCaps = mutable.value.capabilities.optJSONObject("voice")
        val route = CompanionVoiceRouting.decide(
            leaderReachable = mutable.value.leaderReachable || mutable.value.connected,
            realtimeVoiceHealthy = mutable.value.connected && voiceCaps?.optBoolean("realtime") == true,
            hostTtsHealthy = mutable.value.connected && voiceCaps?.optBoolean("tts_ready") == true,
            sttPackStatus = voicePackManager.sttStatus(),
            ttsPackStatus = voicePackManager.ttsStatus(),
            localLlmReady = packManager.isPackReady(),
        )
        if (route.stt == SttVoiceRoute.ON_DEVICE) {
            if (onDeviceListening) {
                stopOnDeviceListen()
            } else {
                startOnDeviceListen()
            }
            return
        }
        if (route.stt == SttVoiceRoute.INSTALL && !mutable.value.connected) {
            mutable.value = mutable.value.copy(
                error = route.error ?: "Install on-device STT in More → Voice before listening offline",
            )
            return
        }
        val realtimeReady = mutable.value.connected && voiceCaps?.optBoolean("realtime") == true
        if (realtimeReady && audioRecord == null && recorder == null) {
            startRealtimeTalk()
            return
        }
        if (audioRecord != null || realtime != null) {
            stopRealtimeTalk()
            return
        }
        if (recorder == null) {
            runCatching {
                recordingFile = File.createTempFile("jarvis-voice", ".m4a", getApplication<Application>().cacheDir)
                @Suppress("DEPRECATION")
                val next = MediaRecorder()
                next.setAudioSource(MediaRecorder.AudioSource.MIC)
                next.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                next.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                next.setOutputFile(recordingFile!!.absolutePath)
                next.prepare(); next.start(); recorder = next
                mutable.value = mutable.value.copy(recording = true, voiceMode = "clip", liveTranscript = "")
            }.onFailure { mutable.value = mutable.value.copy(error = it.message) }
        } else action {
            try {
                recorder?.stop()
                val result = JSONObject(api.raw("/voice/transcribe", "POST", recordingFile!!.readBytes(), contentType = "audio/mp4").toString(Charsets.UTF_8))
                sendNow(result.getString("text"))
            } finally {
                recorder?.release(); recorder = null; recordingFile?.delete()
                mutable.value = mutable.value.copy(recording = false)
            }
        }
    }

    private fun startOnDeviceListen() = action {
        if (!hasRecordAudioPermission()) {
            mutable.value = mutable.value.copy(error = "Microphone permission is required for on-device voice")
            return@action
        }
        stopSpeaking()
        val minBuf = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = try {
            AudioRecord(AudioSource.VOICE_COMMUNICATION, 16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, minBuf * 2)
        } catch (_: SecurityException) {
            mutable.value = mutable.value.copy(error = "Microphone permission is required for on-device voice")
            return@action
        }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            mutable.value = mutable.value.copy(error = "Microphone is unavailable")
            return@action
        }
        audioRecord = record
        onDevicePcm = java.io.ByteArrayOutputStream()
        onDeviceListening = true
        try {
            record.startRecording()
        } catch (_: SecurityException) {
            record.release()
            audioRecord = null
            onDeviceListening = false
            mutable.value = mutable.value.copy(error = "Microphone permission is required for on-device voice")
            return@action
        }
        mutable.value = mutable.value.copy(
            recording = true,
            voiceMode = "on_device",
            liveTranscript = "",
            activity = "Listening on-device…",
            onDeviceVoiceActive = true,
        )
        captureJob = viewModelScope.launch(Dispatchers.IO) {
            val buffer = ByteArray(minBuf.coerceAtLeast(3200))
            while (isActive && onDeviceListening && audioRecord != null) {
                val read = record.read(buffer, 0, buffer.size)
                if (read > 0) onDevicePcm?.write(buffer, 0, read)
            }
        }
    }

    private fun stopOnDeviceListen() = action {
        onDeviceListening = false
        captureJob?.cancel(); captureJob = null
        runCatching { audioRecord?.stop() }
        audioRecord?.release(); audioRecord = null
        mutable.value = mutable.value.copy(recording = false)
        val pcm = onDevicePcm?.toByteArray() ?: ByteArray(0)
        onDevicePcm = null
        if (pcm.isEmpty()) {
            mutable.value = mutable.value.copy(error = "No audio captured for on-device STT")
            voicePackManager.unloadIdle()
            return@action
        }
        try {
            val text = voicePackManager.transcribePcm16le(pcm, 16_000)
            mutable.value = mutable.value.copy(liveTranscript = text, activity = "On-device transcript ready")
            sendNow(text)
        } finally {
            voicePackManager.unloadIdle()
            publishVoiceRoute()
        }
    }

    private fun hasRecordAudioPermission(): Boolean =
        ContextCompat.checkSelfPermission(getApplication(), Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun startRealtimeTalk() = action {
        if (!hasRecordAudioPermission()) {
            mutable.value = mutable.value.copy(error = "Microphone permission is required for realtime voice")
            return@action
        }
        stopSpeaking()
        val session = RealtimeVoiceSession(api, mutable.value.conversationId, mutable.value.selectedVoice, mutable.value.selectedModel)
        realtime = session
        session.connect()
        session.startTurn()
        val minBuf = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = try {
            AudioRecord(AudioSource.VOICE_COMMUNICATION, 16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, minBuf * 2)
        } catch (_: SecurityException) {
            session.close()
            realtime = null
            mutable.value = mutable.value.copy(error = "Microphone permission is required for realtime voice")
            return@action
        }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            session.close()
            realtime = null
            mutable.value = mutable.value.copy(error = "Microphone is unavailable")
            return@action
        }
        audioRecord = record
        try {
            record.startRecording()
        } catch (_: SecurityException) {
            record.release()
            audioRecord = null
            session.close()
            realtime = null
            mutable.value = mutable.value.copy(error = "Microphone permission is required for realtime voice")
            return@action
        }
        mutable.value = mutable.value.copy(recording = true, voiceMode = "realtime", liveTranscript = "", activity = "Listening…")
        ensureTtsWorker()
        captureJob = viewModelScope.launch(Dispatchers.IO) {
            val buffer = ByteArray(minBuf.coerceAtLeast(3200))
            while (isActive && audioRecord != null) {
                val read = record.read(buffer, 0, buffer.size)
                if (read > 0) {
                    try { session.sendPcm(buffer.copyOf(read)) } catch (_: Exception) { break }
                }
            }
        }
        listenJob = viewModelScope.launch {
            try {
                while (isActive) {
                    val event = session.nextEvent()
                    when (event.optString("type")) {
                        "partial", "final" -> mutable.value = mutable.value.copy(
                            liveTranscript = event.optString("text"),
                            activity = if (event.optString("type") == "final") "Thinking…" else "Listening…",
                        )
                        "tts" -> {
                            if (event.optBoolean("final")) continue
                            val data = event.optString("data")
                            if (data.isNotEmpty()) {
                                ttsQueue.offer(Base64.decode(data, Base64.DEFAULT))
                                mutable.value = mutable.value.copy(speaking = true, activity = event.optString("text").ifEmpty { "Speaking" })
                            }
                        }
                        "done" -> {
                            event.optString("conversation_id").takeIf { it.isNotEmpty() }?.let {
                                mutable.value = mutable.value.copy(conversationId = it)
                            }
                            mutable.value = mutable.value.copy(activity = "Ready when you are")
                            refresh()
                            break
                        }
                        "interrupted" -> {
                            ttsQueue.clear(); stopSpeaking()
                            mutable.value = mutable.value.copy(activity = "Interrupted", speaking = false)
                            break
                        }
                        "error" -> throw IllegalStateException(event.optString("detail"))
                    }
                }
            } catch (exc: Exception) {
                mutable.value = mutable.value.copy(error = exc.message)
            }
        }
    }

    private fun stopRealtimeTalk() = action {
        captureJob?.cancel(); captureJob = null
        runCatching { audioRecord?.stop() }
        audioRecord?.release(); audioRecord = null
        mutable.value = mutable.value.copy(recording = false)
        val session = realtime
        if (session != null) {
            runCatching { session.endTurn() }
            // Keep listenJob alive until done/tts finishes; close after a grace period if needed.
            viewModelScope.launch {
                delay(120_000)
                if (listenJob?.isActive == true) {
                    session.interrupt()
                    session.close()
                    listenJob?.cancel()
                    listenJob = null
                    realtime = null
                }
            }
        }
    }

    private fun ensureTtsWorker() {
        if (ttsJob?.isActive == true) return
        ttsJob = viewModelScope.launch(Dispatchers.IO) {
            while (isActive) {
                val audio = ttsQueue.take()
                withContext(Dispatchers.Main) { playAudio(audio) }
                while (mutable.value.speaking && isActive) delay(40)
            }
        }
    }

    fun speak(text: String) = action {
        if (player != null || mutable.value.speaking) { stopSpeaking(); realtime?.interrupt(); return@action }
        val voiceCaps = mutable.value.capabilities.optJSONObject("voice")
        val route = CompanionVoiceRouting.decide(
            leaderReachable = mutable.value.leaderReachable || mutable.value.connected,
            realtimeVoiceHealthy = mutable.value.connected && voiceCaps?.optBoolean("realtime") == true,
            hostTtsHealthy = mutable.value.connected && voiceCaps?.optBoolean("tts_ready") == true,
            sttPackStatus = voicePackManager.sttStatus(),
            ttsPackStatus = voicePackManager.ttsStatus(),
            localLlmReady = packManager.isPackReady(),
        )
        if (route.tts == TtsVoiceRoute.ON_DEVICE) {
            mutable.value = mutable.value.copy(onDeviceVoiceActive = true, activity = "Speaking on-device…")
            try {
                val audio = voicePackManager.synthesize(text.take(6000))
                playAudio(audio)
            } finally {
                voicePackManager.unloadIdle()
                publishVoiceRoute()
            }
            return@action
        }
        if (route.tts == TtsVoiceRoute.INSTALL) {
            mutable.value = mutable.value.copy(
                error = route.error ?: "Install on-device TTS in More → Voice before speaking offline",
            )
            return@action
        }
        val body = JSONObject().put("text", text.take(6000))
        mutable.value.selectedVoice.takeIf { it.isNotEmpty() }?.let { body.put("voice_profile_id", it) }
        val audio = api.raw("/voice/speak", "POST", body.toString().toByteArray())
        playAudio(audio)
    }
    fun previewVoice(profileId: String) = action {
        stopSpeaking()
        val audio = api.raw("/voice/profiles/$profileId/preview", "POST", ByteArray(0))
        playAudio(audio)
    }
    private fun playAudio(audio: ByteArray) {
        val file = File.createTempFile("jarvis-speech", ".wav", getApplication<Application>().cacheDir)
        try {
            file.writeBytes(audio)
            playerFile = file
            player = MediaPlayer().apply {
                setDataSource(file.absolutePath)
                setOnCompletionListener { stopSpeaking() }
                prepare(); start()
            }
            mutable.value = mutable.value.copy(speaking = true)
        } catch (exc: Exception) {
            file.delete()
            playerFile = null
            throw exc
        }
    }
    private fun stopSpeaking() {
        player?.release(); player = null
        playerFile?.delete(); playerFile = null
        mutable.value = mutable.value.copy(speaking = false)
    }
    override fun onCleared() {
        captureJob?.cancel(); listenJob?.cancel(); ttsJob?.cancel()
        onDeviceListening = false
        runCatching { audioRecord?.stop() }; audioRecord?.release()
        realtime?.close()
        recorder?.release(); recordingFile?.delete(); stopSpeaking()
        packManager.unload()
        voicePackManager.unloadIdle()
        super.onCleared()
    }
}
