package com.jarvis.companion

/** Stable pack lifecycle values for Models UI + offline banner (RFC-0108). */
object CompanionPackStatus {
    const val MISSING = "missing"
    const val DOWNLOADING = "downloading"
    const val READY = "ready"
    const val RUNNING = "running"
    const val ERROR = "error"

    val ALL = setOf(MISSING, DOWNLOADING, READY, RUNNING, ERROR)
}
