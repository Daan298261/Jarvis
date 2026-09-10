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
    val attachmentIds: List<String> = emptyList(), val capabilities: JSONObject = JSONObject(),
    val swarm: JSONObject = JSONObject(), val coding: JSONObject = JSONObject(),
    val codingDecisions: List<JSONObject> = emptyList(), val voiceProfiles: List<JSONObject> = emptyList(),
    val selectedVoice: String = "", val presenceMode: String = "orb",
    val liveTranscript: String = "", val voiceMode: String = "clip",
)

fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }

private data class RefreshPayload(
    val capabilities: JSONObject,
    val tasks: List<JSONObject>,
    val models: List<JSONObject>,
    val conversations: List<JSONObject>,
    val schedules: List<JSONObject>,
    val calls: List<JSONObject>,
    val messages: List<JSONObject>,
    val swarm: JSONObject,
    val coding: JSONObject,
    val voices: JSONObject,
)

class CompanionModel(app: Application) : AndroidViewModel(app) {
    val api = (app as JarvisApp).api
    private val companionPrefs = app.getSharedPreferences("companion_ui", Application.MODE_PRIVATE)
    private val mutable = MutableStateFlow(CompanionState(
        selectedVoice = companionPrefs.getString("voice_profile", "") ?: "",
        presenceMode = companionPrefs.getString("presence_mode", "orb").takeIf { it in setOf("orb", "humanoid") } ?: "orb",
    ))
    val state = mutable.asStateFlow()
    private var recorder: MediaRecorder? = null
    private var recordingFile: File? = null
    private var player: MediaPlayer? = null
    private var playerFile: File? = null
    private val outbox = Outbox(app)
    private var foreground = false
    private val sendLock = kotlinx.coroutines.sync.Mutex()
    private var audioRecord: AudioRecord? = null
    private var realtime: RealtimeVoiceSession? = null
    private var captureJob: Job? = null
    private var listenJob: Job? = null
    private val ttsQueue = LinkedBlockingQueue<ByteArray>()
    private var ttsJob: Job? = null
    init {
        runCatching { outbox.read() }.onSuccess { mutable.value = mutable.value.copy(pendingMessage = it != null) }
            .onFailure { mutable.value = mutable.value.copy(error = "Cannot recover pending message: ${it.message}") }
        viewModelScope.launch {
            while (true) {
                if (foreground && api.deviceId.isNotEmpty()) runCatching { refresh() }.onFailure { mutable.value = mutable.value.copy(connected = false, activity = "Reconnecting", error = it.message) }
                delay(4000)
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
            val models = async { api.json("/models").getJSONArray("models").objects() }
            val conversations = async { api.array("/conversations").objects() }
            val schedules = async { api.array("/schedules").objects() }
            val calls = async { api.array("/calls").objects() }
            val messages = async {
                previous.conversationId?.let { api.json("/conversations/$it").getJSONArray("messages").objects() } ?: emptyList()
            }
            val swarm = async { runCatching { api.json("/swarm") }.getOrDefault(previous.swarm) }
            val coding = async { runCatching { api.json("/coding") }.getOrDefault(previousCoding) }
            val voices = async { runCatching { api.json("/voice/profiles") }.getOrDefault(previousVoices) }
            RefreshPayload(capabilities.await(), tasks.await(), models.await(), conversations.await(), schedules.await(), calls.await(),
                messages.await(), swarm.await(), coding.await(), voices.await())
        }
        val active = payload.tasks.firstOrNull { it.optString("status") in listOf("queued", "running", "waiting") }
        val voiceProfiles = payload.voices.optJSONArray("profiles")?.objects() ?: emptyList()
        val selectedVoice = previous.selectedVoice.takeIf { selected ->
            voiceProfiles.any { it.optString("id") == selected && it.optBoolean("available") }
        } ?: payload.voices.optString("active_voice_profile_id").takeIf { activeVoice ->
            voiceProfiles.any { it.optString("id") == activeVoice && it.optBoolean("available") }
        } ?: voiceProfiles.firstOrNull { it.optBoolean("available") }?.optString("id").orEmpty()
        mutable.value = mutable.value.copy(connected = true, activity = active?.optString("activity") ?: "Ready when you are",
            tasks = payload.tasks, models = payload.models, conversations = payload.conversations, schedules = payload.schedules,
            calls = payload.calls, messages = payload.messages, capabilities = payload.capabilities, swarm = payload.swarm,
            coding = payload.coding.optJSONObject("overview") ?: JSONObject(),
            codingDecisions = payload.coding.optJSONObject("decisions")?.optJSONArray("items")?.objects() ?: emptyList(),
            voiceProfiles = voiceProfiles, selectedVoice = selectedVoice,
            pendingMessage = outbox.read() != null)
    }
    fun pair(endpoint: String, pin: String, credential: String) = action {
        api.configure(endpoint, pin)
        if (api.deviceId.isEmpty()) api.pair(credential.trim())
        api.session()
        (getApplication<Application>() as JarvisApp).registerPush()
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
    fun selectModel(value: String) { mutable.value = mutable.value.copy(selectedModel = value) }
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
        check(outbox.read() == null) { "Resolve the pending message before sending another" }
        val state = mutable.value
        val content = JSONObject().put("text", text).put("profile", state.selectedModel)
            .put("attachments", JSONArray(state.attachmentIds))
        state.conversationId?.let { content.put("conversation_id", it) }
        content.put("request_id", UUID.randomUUID().toString())
        outbox.save(JSONObject().put("device", api.deviceId).put("pin", api.pin).put("body", content))
        mutable.value = mutable.value.copy(pendingMessage = true)
        deliverPending()
        } finally { sendLock.unlock() }
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
    private suspend fun uploadNow(uri: Uri) {
        val context = getApplication<Application>()
        val bytes = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            context.contentResolver.openInputStream(uri)?.use { stream ->
                val output = java.io.ByteArrayOutputStream()
                val chunk = ByteArray(32768)
                while (true) {
                    val count = stream.read(chunk)
                    if (count < 0) break
                    require(output.size() + count <= 64 * 1024 * 1024) { "Attachment exceeds 64 MiB" }
                    output.write(chunk, 0, count)
                }
                output.toByteArray()
            } ?: error("Cannot read attachment")
        }
        val type = context.contentResolver.getType(uri) ?: "application/octet-stream"
        val result = JSONObject(api.raw("/attachments", "POST", bytes, contentType = type, filename = uri.lastPathSegment ?: "attachment").toString(Charsets.UTF_8))
        mutable.value = mutable.value.copy(attachmentIds = mutable.value.attachmentIds + result.getString("id"))
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
    fun preferences(notifications: Boolean, calls: Boolean) = action {
        api.json("/preferences", "PUT", JSONObject().put("notifications", notifications).put("critical_calls", calls))
        refresh()
    }
    fun toggleRecord() {
        val realtimeReady = mutable.value.connected &&
            mutable.value.capabilities.optJSONObject("voice")?.optBoolean("realtime") == true
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

    private fun hasRecordAudioPermission(): Boolean =
        ContextCompat.checkSelfPermission(getApplication(), Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun startRealtimeTalk() = action {
        if (!hasRecordAudioPermission()) {
            mutable.value = mutable.value.copy(error = "Microphone permission is required for realtime voice")
            return@action
        }
        stopSpeaking()
        val session = RealtimeVoiceSession(api, mutable.value.conversationId, mutable.value.selectedVoice)
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
        runCatching { audioRecord?.stop() }; audioRecord?.release()
        realtime?.close()
        recorder?.release(); recordingFile?.delete(); stopSpeaking(); super.onCleared()
    }
}
