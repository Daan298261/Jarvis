package com.jarvis.companion

/**
 * Shared companion Home HUD presence phases (RFC-0139), aligned with Desktop
 * presenceState.ts first-match intent:
 * Offline → Error → Approval → Alert → Speaking → Listening → Working → Thinking → Waiting → Idle
 *
 * When Leader is unreachable, idle-offline uses [OFFLINE]; on-device STT/TTS / local model
 * activity still surfaces Speaking / Listening / Thinking (RFC-0139 §6).
 */
enum class PresencePhase {
    OFFLINE,
    ERROR,
    APPROVAL,
    ALERT,
    SPEAKING,
    LISTENING,
    WORKING,
    THINKING,
    WAITING,
    IDLE,
}

/** Minimal task signal for presence — keeps [PresenceVisual] JVM-testable without org.json. */
data class PresenceTaskSignal(
    val status: String,
    val waitingForConfirmation: Boolean = false,
    val hasApproval: Boolean = false,
)

data class PresenceInputs(
    val connected: Boolean,
    val recording: Boolean = false,
    val speaking: Boolean = false,
    val pendingApproval: Boolean = false,
    val systemDegraded: Boolean = false,
    val hardError: Boolean = false,
    val offlineAnswering: Boolean = false,
    val tasks: List<PresenceTaskSignal> = emptyList(),
    val audioLevel: Float = 0f,
    val reducedMotion: Boolean = false,
)

/**
 * Pure visual policy for the companion presence HUD.
 * Offline tip activity ~0.12 is rejected; daylight floor is [OFFLINE_ACTIVITY_FLOOR].
 */
object PresenceVisual {
    /** Tip Offline dead-dim rejected by RFC-0139. */
    const val REJECTED_TIP_OFFLINE_ACTIVITY = 0.12f

    /**
     * Minimum effective activity for Offline / idle-offline so the figure stays
     * daylight-readable (≥ ~0.45). Never collapse toward [REJECTED_TIP_OFFLINE_ACTIVITY].
     */
    const val OFFLINE_ACTIVITY_FLOOR = 0.45f

    /** Connected Idle breathing floor — clearly alive, not a static ghost. */
    const val IDLE_ACTIVITY = 0.48f

    /** Minimum humanoid particle count for a rich multi-orb bust (RFC-0125 + RFC-0139). */
    const val HUMANOID_MIN_PARTICLES = 400

    /** Default companion presence chrome after install / missing preference (RFC-0139). */
    const val DEFAULT_PRESENCE_MODE = "humanoid"

    fun normalizePresenceMode(stored: String?): String =
        stored?.takeIf { it in setOf("orb", "humanoid") } ?: DEFAULT_PRESENCE_MODE

    fun resolvePhase(inputs: PresenceInputs): PresencePhase {
        if (!inputs.connected) {
            // Leader unreachable: idle-offline is Offline; on-device STT/TTS/local model still animate (§6).
            if (inputs.hardError) return PresencePhase.ERROR
            if (inputs.speaking) return PresencePhase.SPEAKING
            if (inputs.recording) return PresencePhase.LISTENING
            if (inputs.offlineAnswering) return PresencePhase.THINKING
            return PresencePhase.OFFLINE
        }
        val active = inputs.tasks.firstOrNull { task ->
            task.status in listOf("queued", "running", "waiting", "failed") ||
                task.waitingForConfirmation ||
                task.hasApproval
        }
        if (inputs.hardError || active?.status == "failed") return PresencePhase.ERROR
        if (inputs.pendingApproval || active?.waitingForConfirmation == true || active?.hasApproval == true) {
            return PresencePhase.APPROVAL
        }
        if (inputs.systemDegraded) return PresencePhase.ALERT
        if (inputs.speaking) return PresencePhase.SPEAKING
        if (inputs.recording) return PresencePhase.LISTENING
        when (active?.status) {
            "running" -> return PresencePhase.WORKING
            "queued" -> return PresencePhase.THINKING
            "waiting" -> return PresencePhase.WAITING
        }
        if (active != null && active.status !in listOf("completed", "cancelled", "failed")) {
            return PresencePhase.THINKING
        }
        return PresencePhase.IDLE
    }

    /**
     * Effective particle / glow activity in 0..1.
     * Offline and idle-offline never drop below [OFFLINE_ACTIVITY_FLOOR].
     */
    fun effectiveActivity(phase: PresencePhase, audioLevel: Float = 0f): Float {
        val base = when (phase) {
            PresencePhase.OFFLINE -> OFFLINE_ACTIVITY_FLOOR
            PresencePhase.IDLE -> IDLE_ACTIVITY
            PresencePhase.WAITING -> 0.52f
            PresencePhase.APPROVAL -> 0.55f
            PresencePhase.LISTENING -> 0.62f
            PresencePhase.THINKING -> 0.72f
            PresencePhase.WORKING -> 0.82f
            PresencePhase.ALERT -> 0.78f
            PresencePhase.ERROR -> 0.88f
            PresencePhase.SPEAKING -> (0.78f + audioLevel.coerceIn(0f, 1f) * 0.18f).coerceAtMost(0.96f)
        }
        val activity = base.coerceIn(OFFLINE_ACTIVITY_FLOOR, 1f)
        // Hard invariant: never ship tip's dead Offline dim.
        check(activity >= OFFLINE_ACTIVITY_FLOOR) {
            "presence activity $activity below daylight floor $OFFLINE_ACTIVITY_FLOOR"
        }
        check(activity > REJECTED_TIP_OFFLINE_ACTIVITY) {
            "presence activity $activity must reject tip dim $REJECTED_TIP_OFFLINE_ACTIVITY"
        }
        return activity
    }

    fun isOfflineReadable(phase: PresencePhase): Boolean =
        phase != PresencePhase.OFFLINE || effectiveActivity(phase) >= OFFLINE_ACTIVITY_FLOOR

    fun animationPeriodMs(phase: PresencePhase, reducedMotion: Boolean): Int {
        if (reducedMotion) return 24_000
        return when (phase) {
            PresencePhase.IDLE, PresencePhase.OFFLINE -> 8_200
            PresencePhase.WAITING, PresencePhase.APPROVAL -> 5_400
            PresencePhase.THINKING -> 3_800
            PresencePhase.LISTENING, PresencePhase.SPEAKING -> 2_800
            PresencePhase.WORKING, PresencePhase.ALERT, PresencePhase.ERROR -> 2_200
        }
    }

    fun motionAmplitude(phase: PresencePhase, reducedMotion: Boolean): Float {
        if (reducedMotion) return 0.08f
        return when (phase) {
            PresencePhase.OFFLINE -> 0.35f
            PresencePhase.IDLE -> 0.42f
            PresencePhase.WAITING, PresencePhase.APPROVAL -> 0.38f
            PresencePhase.LISTENING -> 0.55f
            PresencePhase.THINKING -> 0.68f
            PresencePhase.WORKING -> 0.92f
            PresencePhase.SPEAKING -> 0.85f
            PresencePhase.ALERT, PresencePhase.ERROR -> 1.0f
        }
    }
}
