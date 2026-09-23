package com.jarvis.companion

/** Stable voice pack lifecycle values (RFC-0140) — same contract as CompanionPackStatus. */
object CompanionVoicePackStatus {
    const val MISSING = "missing"
    const val DOWNLOADING = "downloading"
    const val READY = "ready"
    const val RUNNING = "running"
    const val ERROR = "error"

    val ALL = setOf(MISSING, DOWNLOADING, READY, RUNNING, ERROR)
    val USABLE = setOf(READY, RUNNING)
}
