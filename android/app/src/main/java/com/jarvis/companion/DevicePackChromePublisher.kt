package com.jarvis.companion

/** Maps D1 pack runtime into UX [DevicePackChromeState] (RFC-0108). */
object DevicePackChromePublisher {
    fun toDeviceStatus(packStatus: String): DevicePackStatus = when (packStatus) {
        CompanionPackStatus.DOWNLOADING -> DevicePackStatus.DOWNLOADING
        CompanionPackStatus.READY -> DevicePackStatus.READY
        CompanionPackStatus.RUNNING -> DevicePackStatus.RUNNING
        CompanionPackStatus.ERROR -> DevicePackStatus.ERROR
        else -> DevicePackStatus.MISSING
    }

    /** Pure mapping: all file facts come from [files], so this is safe on the main thread. */
    fun buildState(manager: CompanionPackManager, companionState: CompanionState, files: PackFileSnapshot): DevicePackChromeState {
        val selected = manager.selectedPack()
        val status = toDeviceStatus(companionState.localPackStatus)
        val progress = companionState.localPackProgress
        return DevicePackChromeState(
            status = status,
            selectedPackId = manager.selectedPackId(),
            selectedPackLabel = selected?.label ?: "",
            bytesOnDisk = files.storageBytes,
            downloadProgress = if (status == DevicePackStatus.DOWNLOADING) progress / 100f else null,
            error = companionState.localPackError.takeIf { it.isNotBlank() },
            availablePacks = manager.catalog().map { pack ->
                DevicePackOption(id = pack.id, label = pack.label, sizeBytes = pack.sizeBytes,
                    minRamMb = pack.minRamMb, installed = files.installed[pack.id] == true, canDownload = pack.url.isNotBlank(),
                    resumeBytes = files.resumeBytes[pack.id] ?: 0L)
            },
            downloads = companionState.modelDownloads,
            nativeRuntimeBundled = manager.engine.isRuntimeAvailable(),
        )
    }

    /** Reads pack files on IO via [CompanionPackManager.packFileSnapshot], then publishes on the caller. */
    suspend fun publish(model: CompanionModel, chrome: CompanionDeviceModelChrome, companionState: CompanionState) {
        chrome.publish(buildState(model.packManager, companionState, model.packManager.packFileSnapshot()))
    }
}
