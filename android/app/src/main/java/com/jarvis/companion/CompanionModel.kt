package com.jarvis.companion

import android.app.Application
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

data class CompanionState(
    val connected: Boolean = false, val activity: String = "Offline", val error: String? = null,
    val busy: Boolean = false, val recording: Boolean = false, val speaking: Boolean = false, val pendingMessage: Boolean = false,
    val tasks: List<JSONObject> = emptyList(), val models: List<JSONObject> = emptyList(),
    val messages: List<JSONObject> = emptyList(), val conversations: List<JSONObject> = emptyList(),
    val schedules: List<JSONObject> = emptyList(), val calls: List<JSONObject> = emptyList(),
    val conversationId: String? = null, val selectedModel: String = "auto",
    val attachmentIds: List<String> = emptyList(), val capabilities: JSONObject = JSONObject()
)

fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }

class CompanionModel(app: Application) : AndroidViewModel(app) {
    val api = (app as JarvisApp).api
    private val mutable = MutableStateFlow(CompanionState())
    val state = mutable.asStateFlow()
    private var recorder: MediaRecorder? = null
    private var recordingFile: File? = null
    private var player: MediaPlayer? = null
    private val outbox = Outbox(app)
    private var foreground = false
    private val sendLock = kotlinx.coroutines.sync.Mutex()
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
        val capabilities = api.json("/capabilities")
        val tasks = api.array("/tasks").objects()
        val models = api.json("/models").getJSONArray("models").objects()
        val conversations = api.array("/conversations").objects()
        val schedules = api.array("/schedules").objects()
        val calls = api.array("/calls").objects()
        val cid = mutable.value.conversationId
        val messages = if (cid != null) api.json("/conversations/$cid").getJSONArray("messages").objects() else emptyList()
        val active = tasks.firstOrNull { it.optString("status") in listOf("queued", "running", "waiting") }
        mutable.value = mutable.value.copy(connected = true, activity = active?.optString("activity") ?: "Ready when you are",
            tasks = tasks, models = models, conversations = conversations, schedules = schedules, calls = calls, messages = messages, capabilities = capabilities,
            pendingMessage = outbox.read() != null)
    }
    fun pair(endpoint: String, pin: String, invitation: String) = action {
        api.configure(endpoint, pin)
        if (api.deviceId.isEmpty()) api.pair(invitation.trim())
        api.session()
        (getApplication<Application>() as JarvisApp).registerPush()
        refresh()
    }
    fun selectModel(value: String) { mutable.value = mutable.value.copy(selectedModel = value) }
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
    fun upload(uri: Uri) = action {
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
    fun schedule(prompt: String, instant: java.time.ZonedDateTime, recurrence: String) = action {
        api.json("/schedules", "POST", JSONObject().put("prompt", prompt).put("next_run", instant.toEpochSecond()).put("timezone", instant.zone.id)
            .put("recurrence", recurrence).put("profile", mutable.value.selectedModel))
        refresh()
    }
    fun pauseSchedule(id: String) = action { api.json("/schedules/$id/pause", "POST"); refresh() }
    fun preferences(notifications: Boolean, calls: Boolean) = action {
        api.json("/preferences", "PUT", JSONObject().put("notifications", notifications).put("critical_calls", calls))
        refresh()
    }
    fun toggleRecord() {
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
                mutable.value = mutable.value.copy(recording = true)
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
    fun speak(text: String) = action {
        if (player != null) { stopSpeaking(); return@action }
        val audio = api.raw("/voice/speak", "POST", JSONObject().put("text", text.take(6000)).toString().toByteArray())
        val file = File.createTempFile("jarvis-speech", ".wav", getApplication<Application>().cacheDir)
        file.writeBytes(audio)
        player = MediaPlayer().apply {
            setDataSource(file.absolutePath)
            setOnCompletionListener { stopSpeaking(); file.delete() }
            prepare(); start()
        }
        mutable.value = mutable.value.copy(speaking = true)
    }
    private fun stopSpeaking() { player?.release(); player = null; mutable.value = mutable.value.copy(speaking = false) }
    override fun onCleared() { recorder?.release(); recordingFile?.delete(); stopSpeaking(); super.onCleared() }
}
