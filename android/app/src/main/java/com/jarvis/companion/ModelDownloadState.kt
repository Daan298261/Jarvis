package com.jarvis.companion

enum class ModelDownloadStage { CONNECTING, DOWNLOADING, RETRYING, VERIFYING, READY, PAUSED, ERROR }

data class ModelDownloadState(
    val packId: String,
    val label: String,
    val stage: ModelDownloadStage = ModelDownloadStage.CONNECTING,
    val receivedBytes: Long = 0,
    val totalBytes: Long = 0,
    val bytesPerSecond: Long = 0,
    val detail: String = "",
) {
    val active: Boolean get() = stage in setOf(ModelDownloadStage.CONNECTING, ModelDownloadStage.DOWNLOADING,
        ModelDownloadStage.RETRYING, ModelDownloadStage.VERIFYING)
    val fraction: Float? get() = when {
        stage == ModelDownloadStage.READY -> 1f
        totalBytes > 0 && stage in setOf(ModelDownloadStage.DOWNLOADING, ModelDownloadStage.PAUSED) ->
            (receivedBytes.toDouble() / totalBytes).toFloat().coerceIn(0f, 1f)
        else -> null
    }
    val statusLabel: String get() = when (stage) {
        ModelDownloadStage.CONNECTING -> "Connecting…"
        ModelDownloadStage.DOWNLOADING -> "Downloading · ${((fraction ?: 0f) * 100).toInt()}%"
        ModelDownloadStage.RETRYING -> "Connection interrupted · retrying…"
        ModelDownloadStage.VERIFYING -> "Verifying download…"
        ModelDownloadStage.READY -> "Ready on this phone"
        ModelDownloadStage.PAUSED -> "Paused · saved for resume"
        ModelDownloadStage.ERROR -> "Download needs attention"
    }
}
