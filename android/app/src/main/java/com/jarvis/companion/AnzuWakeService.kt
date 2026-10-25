package com.jarvis.companion

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.KeywordSpotter
import com.k2fsa.sherpa.onnx.KeywordSpotterConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow

object WakeAudioState {
    @Volatile var busy = false
    val status = MutableStateFlow("Wake word off")
}

class AnzuWakeService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null
    private var microphone: AudioRecord? = null
    override fun onBind(intent: Intent?) = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action != "enable") {
            WakeSettings(this).enabled = false
            stopSelf()
            return START_NOT_STICKY
        }
        if (job?.isActive == true) return START_NOT_STICKY
        if (!getSystemService(android.app.role.RoleManager::class.java).isRoleHeld(android.app.role.RoleManager.ROLE_ASSISTANT)) {
            WakeSettings(this).enabled = false
            WakeAudioState.status.value = "Select ANZU as your default assistant, then enable wake listening"
            stopSelf(); return START_NOT_STICKY
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            WakeAudioState.status.value = "Microphone permission is required"
            stopSelf(); return START_NOT_STICKY
        }
        try {
            val notifications = getSystemService(NotificationManager::class.java)
            notifications.createNotificationChannel(NotificationChannel("anzu_wake", "ANZU wake word", NotificationManager.IMPORTANCE_LOW))
            val stop = PendingIntent.getService(this, 1, Intent(this, AnzuWakeService::class.java).setAction("stop"),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val open = PendingIntent.getActivity(this, 2, Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val notification = NotificationCompat.Builder(this, "anzu_wake").setSmallIcon(R.drawable.ic_jarvis)
                .setContentTitle("ANZU wake listening").setContentText("Listening for your saved wake phrases. Audio stays on this phone.")
                .setContentIntent(open).setOngoing(true).addAction(0, "Stop listening", stop).build()
            startForeground(215, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } catch (error: Exception) {
            WakeAudioState.status.value = "Open ANZU to enable wake listening: ${error.message}"
            stopSelf(); return START_NOT_STICKY
        }
        job = scope.launch {
            var spotter: KeywordSpotter? = null
            var stream: com.k2fsa.sherpa.onnx.OnlineStream? = null
            try {
                val settings = WakeSettings(this@AnzuWakeService)
                val keywords = settings.keywords(this@AnzuWakeService)
                spotter = KeywordSpotter(assets, KeywordSpotterConfig(
                    featConfig = FeatureConfig(sampleRate = 16000, featureDim = 80),
                    modelConfig = OnlineModelConfig(transducer = OnlineTransducerModelConfig(
                        encoder = "wake/encoder.onnx", decoder = "wake/decoder.onnx", joiner = "wake/joiner.onnx"),
                        tokens = "wake/tokens.txt", numThreads = 1, provider = "cpu", modelingUnit = "cjkchar"),
                    keywordsFile = "wake/keywords.txt", keywordsScore = 1.5f, keywordsThreshold = settings.threshold))
                stream = spotter.createStream(keywords)
                var pauseUntil = 0L
                val buffer = ShortArray(1600)
                while (isActive) {
                    val audio = getSystemService(AudioManager::class.java)
                    val keyguard = getSystemService(android.app.KeyguardManager::class.java)
                    if (WakeAudioState.busy || audio.mode != AudioManager.MODE_NORMAL || audio.isMusicActive ||
                        keyguard.isKeyguardLocked || SystemClock.elapsedRealtime() < pauseUntil) {
                        releaseMic()
                        WakeAudioState.status.value = when {
                            keyguard.isKeyguardLocked -> "Wake listening paused while phone is locked"
                            WakeAudioState.busy -> "Wake listening paused during ANZU speech"
                            audio.mode != AudioManager.MODE_NORMAL -> "Wake listening paused during a call"
                            audio.isMusicActive -> "Wake listening paused during audio playback"
                            else -> "Wake listening cooling down"
                        }
                        delay(250)
                        continue
                    }
                    if (microphone == null) {
                        val size = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
                        check(size > 0) { "Microphone configuration is unavailable" }
                        microphone = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000,
                            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, size.coerceAtLeast(6400))
                        check(microphone?.state == AudioRecord.STATE_INITIALIZED) { "Microphone could not be initialized" }
                        microphone?.startRecording()
                        spotter.reset(stream)
                    }
                    WakeAudioState.status.value = "Listening for ${settings.phrases}"
                    val count = microphone?.read(buffer, 0, buffer.size) ?: 0
                    check(count >= 0) { "Microphone became unavailable" }
                    if (count == 0) { delay(100); continue }
                    stream.acceptWaveform(FloatArray(count) { buffer[it] / 32768f }, 16000)
                    while (spotter.isReady(stream)) {
                        spotter.decode(stream)
                        if (spotter.getResult(stream).keyword.isNotBlank()) {
                            spotter.reset(stream)
                            releaseMic()
                            pauseUntil = SystemClock.elapsedRealtime() + 10_000
                            withContext(Dispatchers.Main) {
                                val assistant = AnzuVoiceInteractionService.current
                                if (assistant != null) assistant.showSession(android.os.Bundle().apply { putBoolean("anzu_voice", true) },
                                    android.service.voice.VoiceInteractionSession.SHOW_WITH_ASSIST)
                                else WakeAudioState.status.value = "Select ANZU as your default assistant first"
                            }
                            break
                        }
                    }
                }
            } catch (error: Exception) {
                if (error !is CancellationException) WakeAudioState.status.value = "Wake listening stopped: ${error.message}"
            } catch (error: LinkageError) {
                WakeAudioState.status.value = "Wake runtime could not load. Update ANZU: ${error.message}"
            } finally {
                releaseMic()
                stream?.release(); spotter?.release()
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }
    private fun releaseMic() {
        val record = microphone
        microphone = null
        runCatching { record?.stop() }
        record?.release()
    }
    override fun onDestroy() {
        scope.cancel()
        releaseMic()
        if (WakeAudioState.status.value.startsWith("Listening") || WakeAudioState.status.value.startsWith("Wake listening paused"))
            WakeAudioState.status.value = "Wake word off"
        super.onDestroy()
    }
}
