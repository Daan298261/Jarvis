package com.jarvis.companion

/**
 * On-device STT engine contract (RFC-0140).
 * Implementations must never invent transcripts — failures are explicit errors.
 */
interface OnDeviceSttEngine {
    val runtimeName: String
    fun isRuntimeAvailable(): Boolean
    /** Load model weights. Returns null on success, actionable error otherwise. */
    fun load(modelPath: String, engineId: String): String?
    fun transcribe(pcm16le: ByteArray, sampleRate: Int): Result<String>
    fun unload()
}

/**
 * On-device TTS engine contract (RFC-0140).
 * Must never return a fake/silent waveform as success.
 */
interface OnDeviceTtsEngine {
    val runtimeName: String
    fun isRuntimeAvailable(): Boolean
    fun load(packDirectory: String, engineId: String): String?
    /** WAV bytes (PCM16LE with header) on success. */
    fun synthesize(text: String): Result<ByteArray>
    fun unload()
}

/**
 * whisper.cpp JNI STT. When the native runtime is not linked in this APK build,
 * load()/transcribe() return honest errors — never a canned transcript.
 */
class WhisperCppSttEngine : OnDeviceSttEngine {
    override val runtimeName: String = "whisper.cpp"
    private var loadedPath: String? = null

    override fun isRuntimeAvailable(): Boolean = VoiceNativeBridge.isWhisperLoaded()

    override fun load(modelPath: String, engineId: String): String? {
        if (!isRuntimeAvailable()) {
            return "On-device STT runtime (whisper.cpp) is missing from this APK build"
        }
        val err = VoiceNativeBridge.nativeWhisperLoad(modelPath)
        if (err.isNotBlank()) return err
        loadedPath = modelPath
        return null
    }

    override fun transcribe(pcm16le: ByteArray, sampleRate: Int): Result<String> {
        if (!isRuntimeAvailable() || loadedPath == null) {
            return Result.failure(IllegalStateException("On-device STT is not loaded"))
        }
        val out = VoiceNativeBridge.nativeWhisperTranscribe(pcm16le, sampleRate)
        if (out.startsWith("error:")) {
            return Result.failure(IllegalStateException(out.removePrefix("error:")))
        }
        if (out.isBlank()) {
            return Result.failure(IllegalStateException("On-device STT returned empty text"))
        }
        return Result.success(out)
    }

    override fun unload() {
        if (isRuntimeAvailable()) VoiceNativeBridge.nativeWhisperUnload()
        loadedPath = null
    }
}

/**
 * Pocket TTS (preferred) with Piper ONNX fallback.
 * Requires native ONNX voice bridge; honest error when unavailable.
 */
class PocketOrPiperTtsEngine : OnDeviceTtsEngine {
    override val runtimeName: String = "pocket-tts-onnx|piper-onnx"
    private var loadedDir: String? = null
    private var engineId: String = ""

    override fun isRuntimeAvailable(): Boolean = VoiceNativeBridge.isTtsLoaded()

    override fun load(packDirectory: String, engineId: String): String? {
        if (!isRuntimeAvailable()) {
            return "On-device TTS runtime is missing from this APK build (need Pocket TTS / Piper ONNX native)"
        }
        val err = VoiceNativeBridge.nativeTtsLoad(packDirectory, engineId)
        if (err.isNotBlank()) return err
        loadedDir = packDirectory
        this.engineId = engineId
        return null
    }

    override fun synthesize(text: String): Result<ByteArray> {
        if (!isRuntimeAvailable() || loadedDir == null) {
            return Result.failure(IllegalStateException("On-device TTS is not loaded"))
        }
        if (text.isBlank()) {
            return Result.failure(IllegalArgumentException("Nothing to speak"))
        }
        val audio = VoiceNativeBridge.nativeTtsSynthesize(text)
        if (audio == null || audio.isEmpty()) {
            return Result.failure(IllegalStateException("On-device TTS produced no audio"))
        }
        // Reject near-silent buffers that would look like soft-fail success.
        if (isNearSilentPcmWav(audio)) {
            return Result.failure(IllegalStateException("On-device TTS returned near-silent audio — refusing soft-fail"))
        }
        return Result.success(audio)
    }

    override fun unload() {
        if (isRuntimeAvailable()) VoiceNativeBridge.nativeTtsUnload()
        loadedDir = null
        engineId = ""
    }

    companion object {
        fun isNearSilentPcmWav(wav: ByteArray): Boolean {
            if (wav.size < 44) return true
            var sum = 0L
            var samples = 0
            var i = 44
            while (i + 1 < wav.size) {
                val sample = (wav[i].toInt() and 0xff) or (wav[i + 1].toInt() shl 8)
                val signed = sample.toShort().toInt()
                sum += kotlin.math.abs(signed)
                samples++
                i += 2
            }
            if (samples == 0) return true
            return (sum / samples) < 8
        }
    }
}

/**
 * Speakable chunker for on-device Pocket TTS (RFC-0204).
 * Strips markdown/code/URLs, then splits into sentence groups that fit the LM cache
 * and the 40 s native frame cap (~500 frames). No text is dropped.
 */
object SpeakableTtsChunker {
    const val MAX_CHUNK_CHARS = 360

    fun forSpeech(text: String): String {
        var cleaned = text.replace("\r\n", "\n")
        cleaned = FENCED_CODE.replace(cleaned, " ")
        cleaned = INLINE_CODE.replace(cleaned, " ")
        cleaned = MD_LINK.replace(cleaned) { it.groupValues[1] }
        cleaned = URL.replace(cleaned, " ")
        cleaned = HEADING.replace(cleaned, " ")
        cleaned = MD_EMPHASIS.replace(cleaned, "$1")
        return cleaned.replace(WHITESPACE, " ").trim()
    }

    fun chunk(text: String, maxChars: Int = MAX_CHUNK_CHARS): List<String> {
        val spoken = forSpeech(text)
        if (spoken.isEmpty()) return emptyList()
        val sentences = SENTENCE.split(spoken).map { it.trim() }.filter { it.isNotEmpty() }
        val pieces = if (sentences.isEmpty()) listOf(spoken) else sentences
        val out = ArrayList<String>()
        val current = StringBuilder()
        fun flush() {
            val piece = current.toString().trim()
            if (piece.isNotEmpty()) out.add(piece)
            current.clear()
        }
        for (sentence in pieces) {
            if (sentence.length > maxChars) {
                flush()
                var rest = sentence
                while (rest.length > maxChars) {
                    val cut = rest.lastIndexOf(' ', maxChars).let { if (it < 8) maxChars else it }
                    out.add(rest.substring(0, cut).trim())
                    rest = rest.substring(cut).trim()
                }
                if (rest.isNotEmpty()) current.append(rest)
                continue
            }
            val candidate = if (current.isEmpty()) sentence else "${current} $sentence"
            if (candidate.length > maxChars) {
                flush()
                current.append(sentence)
            } else {
                if (current.isNotEmpty()) current.append(' ')
                current.append(sentence)
            }
        }
        flush()
        return out
    }

    private val FENCED_CODE = Regex("```[\\s\\S]*?```")
    private val INLINE_CODE = Regex("`[^`]*`")
    private val MD_LINK = Regex("\\[([^\\]]+)\\]\\([^)]+\\)")
    private val URL = Regex("https?://\\S+", RegexOption.IGNORE_CASE)
    private val HEADING = Regex("(?m)^#+\\s+.*$")
    private val MD_EMPHASIS = Regex("[*_~]{1,2}([^*_~]+)[*_~]{1,2}")
    private val WHITESPACE = Regex("\\s+")
    private val SENTENCE = Regex("(?<=[.!?])\\s+")
}

object VoiceNativeBridge {
    private var whisperLoaded = false
    private var ttsLoaded = false

    init {
        whisperLoaded = runCatching {
            System.loadLibrary("jarvis_whisper")
            true
        }.getOrDefault(false)
        ttsLoaded = runCatching {
            System.loadLibrary("jarvis_voice_tts")
            true
        }.getOrDefault(false)
    }

    fun isWhisperLoaded(): Boolean = whisperLoaded
    fun isTtsLoaded(): Boolean = ttsLoaded

    external fun nativeWhisperLoad(modelPath: String): String
    external fun nativeWhisperTranscribe(pcm16le: ByteArray, sampleRate: Int): String
    external fun nativeWhisperUnload()

    external fun nativeTtsLoad(packDirectory: String, engineId: String): String
    external fun nativeTtsSynthesize(text: String): ByteArray?
    external fun nativeTtsUnload()
}
