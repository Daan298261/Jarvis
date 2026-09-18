package com.jarvis.companion.device

/** RFC-0108 on-device pack lifecycle (companion Models UI). */
enum class DevicePackStatus {
    MISSING,
    DOWNLOADING,
    READY,
    RUNNING,
    ERROR,
}

data class DeviceModelPackDescriptor(
    val id: String,
    val label: String,
    val filename: String,
    val downloadUrl: String,
    val expectedBytes: Long,
)

data class DevicePackUiState(
    val status: DevicePackStatus = DevicePackStatus.MISSING,
    val selectedPack: DeviceModelPackDescriptor = DeviceModelPackCatalog.defaultPack,
    val bytesOnDisk: Long = 0,
    /** 0.0–1.0 while [status] is DOWNLOADING; null otherwise. */
    val downloadProgress: Float? = null,
    val error: String? = null,
)

/** Pure routing helper (unit-tested). */
fun useOnDeviceInference(leaderConnected: Boolean, packStatus: DevicePackStatus): Boolean =
    !leaderConnected && packStatus in setOf(DevicePackStatus.READY, DevicePackStatus.RUNNING)

fun offlineChatBanner(
    leaderConnected: Boolean,
    paired: Boolean,
    packStatus: DevicePackStatus,
): String? {
    if (leaderConnected || !paired) return null
    return when (packStatus) {
        DevicePackStatus.MISSING, DevicePackStatus.ERROR ->
            "Leader unreachable — install a companion model pack under More → Models."
        DevicePackStatus.DOWNLOADING ->
            "Leader unreachable — model pack downloading…"
        DevicePackStatus.READY, DevicePackStatus.RUNNING ->
            "Leader unreachable — answering on-device."
    }
}
