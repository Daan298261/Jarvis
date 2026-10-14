package com.jarvis.companion

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** RFC-0108 on-device pack lifecycle values exposed to the Models chrome (D1 publishes). */
enum class DevicePackStatus {
    MISSING,
    DOWNLOADING,
    READY,
    RUNNING,
    ERROR,
}

data class DevicePackOption(
    val id: String,
    val label: String,
)

data class DevicePackChromeState(
    val status: DevicePackStatus = DevicePackStatus.MISSING,
    val selectedPackId: String = "",
    val selectedPackLabel: String = "",
    val bytesOnDisk: Long = 0,
    val downloadProgress: Float? = null,
    val error: String? = null,
    val availablePacks: List<DevicePackOption> = emptyList(),
    val nativeRuntimeBundled: Boolean = false,
)

/**
 * Thin companion-facing surface for Models UI + offline banner.
 * D1 binds [actions] and calls [publish] from runtime / [CompanionModel] routing.
 */
interface DevicePackChromeActions {
    fun downloadSelectedPack()
    fun deleteSelectedPack()
    fun selectPack(packId: String)
}

class CompanionDeviceModelChrome {
    private val mutable = MutableStateFlow(DevicePackChromeState())
    val state: StateFlow<DevicePackChromeState> = mutable.asStateFlow()

    @Volatile
    var actions: DevicePackChromeActions? = null

    fun publish(next: DevicePackChromeState) {
        mutable.value = next
    }

    fun downloadSelectedPack() {
        actions?.downloadSelectedPack()
    }

    fun deleteSelectedPack() {
        actions?.deleteSelectedPack()
    }

    fun selectPack(packId: String) {
        actions?.selectPack(packId)
    }
}

fun offlineChatBanner(
    leaderConnected: Boolean,
    paired: Boolean,
    packStatus: DevicePackStatus,
): String? {
    if (leaderConnected) return null
    val where = if (paired) "ANZU desktop unreachable" else "No desktop paired"
    return when (packStatus) {
        DevicePackStatus.MISSING, DevicePackStatus.ERROR ->
            "$where — download or load a model under More → Models to chat on this phone."
        DevicePackStatus.DOWNLOADING ->
            "$where — model downloading…"
        DevicePackStatus.READY, DevicePackStatus.RUNNING ->
            if (paired) "$where — answering on this phone. Chats sync when the desktop is back."
            else "Answering on this phone. Conversations stay on this device."
    }
}
