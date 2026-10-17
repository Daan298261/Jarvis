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

    fun buildState(model: CompanionModel, companionState: CompanionState): DevicePackChromeState {
        val manager = model.packManager
        val selected = manager.selectedPack()
        val status = toDeviceStatus(companionState.localPackStatus)
        val progress = companionState.localPackProgress
        return DevicePackChromeState(
            status = status,
            selectedPackId = manager.selectedPackId(),
            selectedPackLabel = selected?.label ?: "",
            bytesOnDisk = manager.storageBytes(),
            downloadProgress = if (status == DevicePackStatus.DOWNLOADING) progress / 100f else null,
            error = companionState.localPackError.takeIf { it.isNotBlank() },
            availablePacks = manager.catalog().map { pack ->
                DevicePackOption(id = pack.id, label = pack.label, sizeBytes = pack.sizeBytes,
                    minRamMb = pack.minRamMb, installed = manager.isPackInstalled(pack), canDownload = pack.url.isNotBlank(),
                    resumeBytes = java.io.File(manager.packRoot(), "${pack.filename}.partial").length())
            },
            downloads = companionState.modelDownloads,
            nativeRuntimeBundled = manager.engine.isRuntimeAvailable(),
        )
    }

    fun publish(model: CompanionModel, chrome: CompanionDeviceModelChrome, companionState: CompanionState) {
        chrome.publish(buildState(model, companionState))
    }
}
