package com.jarvis.companion

/**
 * RFC-0140 §5 local-vs-gateway voice routing.
 * Online prefers Leader/Kokoro — on-device packs must not silently replace host neural.
 */
enum class VoiceRouteMode {
    ONLINE_HOST,
    FALLBACK_A,
    GRID_DOWN_B,
}

enum class SttVoiceRoute {
    GATEWAY,
    ON_DEVICE,
    /** Android's built-in speech recognizer (offline when the phone has the language pack). */
    PLATFORM,
    INSTALL,
}

enum class TtsVoiceRoute {
    HOST_NEURAL,
    ON_DEVICE,
    /** Android's built-in TextToSpeech engine. */
    PLATFORM,
    INSTALL,
}

data class VoiceRouteDecision(
    val mode: VoiceRouteMode,
    val stt: SttVoiceRoute,
    val tts: TtsVoiceRoute,
    val banner: String? = null,
    val error: String? = null,
    val onDeviceIndicator: Boolean = false,
)

object CompanionVoiceRouting {
    fun decide(
        leaderReachable: Boolean,
        realtimeVoiceHealthy: Boolean,
        hostTtsHealthy: Boolean,
        sttPackStatus: String,
        ttsPackStatus: String,
        localLlmReady: Boolean = false,
        preferOnDeviceFrontend: Boolean = false,
        platformSttAvailable: Boolean = false,
        platformTtsAvailable: Boolean = false,
    ): VoiceRouteDecision {
        val sttReady = sttPackStatus in CompanionVoicePackStatus.USABLE
        val ttsReady = ttsPackStatus in CompanionVoicePackStatus.USABLE
        // ANZU's own packs (Whisper / Pocket TTS) win; Android's engines cover a phone without them.
        fun localStt() = when {
            sttReady -> SttVoiceRoute.ON_DEVICE
            platformSttAvailable -> SttVoiceRoute.PLATFORM
            else -> SttVoiceRoute.INSTALL
        }
        fun localTts() = when {
            ttsReady -> TtsVoiceRoute.ON_DEVICE
            platformTtsAvailable -> TtsVoiceRoute.PLATFORM
            else -> TtsVoiceRoute.INSTALL
        }
        fun usesPlatform(stt: SttVoiceRoute, tts: TtsVoiceRoute) = stt == SttVoiceRoute.PLATFORM || tts == TtsVoiceRoute.PLATFORM

        if (leaderReachable && realtimeVoiceHealthy && hostTtsHealthy && !preferOnDeviceFrontend) {
            return VoiceRouteDecision(
                mode = VoiceRouteMode.ONLINE_HOST,
                stt = SttVoiceRoute.GATEWAY,
                tts = TtsVoiceRoute.HOST_NEURAL,
            )
        }

        if (leaderReachable && (!realtimeVoiceHealthy || !hostTtsHealthy)) {
            val stt = localStt()
            val tts = localTts()
            val error = if (stt == SttVoiceRoute.INSTALL || tts == TtsVoiceRoute.INSTALL) {
                "Host voice failed and on-device voice packs are not installed — open More → Voice"
            } else {
                null
            }
            return VoiceRouteDecision(
                mode = VoiceRouteMode.FALLBACK_A,
                stt = stt,
                tts = tts,
                banner = when {
                    error != null -> null
                    usesPlatform(stt, tts) -> "Host voice unavailable — using this phone's built-in voice"
                    else -> "Host voice unavailable — using on-device voice"
                },
                error = error,
                onDeviceIndicator = error == null,
            )
        }

        if (!leaderReachable) {
            val mode = if (localLlmReady) VoiceRouteMode.GRID_DOWN_B else VoiceRouteMode.FALLBACK_A
            val stt = localStt()
            val tts = localTts()
            val error = if (stt == SttVoiceRoute.INSTALL || tts == TtsVoiceRoute.INSTALL) {
                "ANZU desktop unreachable — install on-device voice packs in More → Voice"
            } else {
                null
            }
            return VoiceRouteDecision(
                mode = mode,
                stt = stt,
                tts = tts,
                banner = when {
                    error != null -> null
                    usesPlatform(stt, tts) -> "This phone's built-in voice (ANZU desktop unreachable)"
                    else -> "On-device voice (ANZU desktop unreachable)"
                },
                error = error,
                onDeviceIndicator = error == null,
            )
        }

        // Optional front-end while online still hands off to Leader for authoritative speech.
        return VoiceRouteDecision(
            mode = VoiceRouteMode.ONLINE_HOST,
            stt = SttVoiceRoute.GATEWAY,
            tts = TtsVoiceRoute.HOST_NEURAL,
            banner = "On-device front-end active — Leader remains authoritative",
            onDeviceIndicator = false,
        )
    }
}
