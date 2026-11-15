package com.jarvis.companion

/** Test helper: downloads whichever pack is currently selected (production downloads by pack id). */
suspend fun CompanionPackManager.downloadSelected(onProgress: (Int) -> Unit = {}) =
    downloadPack(selectedPack() ?: error("No pack selected"), onProgress)
