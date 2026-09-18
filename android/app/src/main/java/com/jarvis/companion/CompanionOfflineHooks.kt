package com.jarvis.companion

import org.json.JSONArray
import org.json.JSONObject

/**
 * UX wiring surface for RFC-0108 (D1). Prefer [JarvisApp.deviceModelChrome] +
 * [DevicePackChromeState] for Models UI + offline banner (PR #308). JSON helpers remain for
 * diagnostics; do not edit MainActivity chrome in the D1 PR.
 */
object CompanionOfflineHooks {
    /**
     * JSON snapshot for Models row + offline banner.
     *
     * Keys: `leader_reachable`, `routing_mode`, `routing_reason`, `local_pack_status`
     * (`missing`|`downloading`|`ready`|`running`|`error`), `local_pack_id`, `local_pack_label`,
     * `local_pack_progress` (0–100), `local_pack_storage_bytes`, `offline_queue_depth`,
     * `offline_answering`, `runtime_available`, `engine`, `packs` (catalog), `offline_banner_suggestion`.
     */
    fun statusSnapshot(model: CompanionModel): JSONObject {
        val state = model.state.value
        val routing = CompanionRouting.decide(
            leaderReachable = state.leaderReachable,
            packStatus = state.localPackStatus,
            resourceBlocked = state.localPackError.takeIf { it.isNotBlank() },
            hasStalePendingOnlineOutbox = state.pendingMessage,
        )
        val selected = model.packManager.selectedPack()
        return JSONObject()
            .put("leader_reachable", state.leaderReachable)
            .put("routing_mode", routing.mode.name)
            .put("routing_reason", routing.reason)
            .put("local_pack_status", state.localPackStatus)
            .put("local_pack_id", model.packManager.selectedPackId())
            .put("local_pack_label", selected?.label ?: "")
            .put("local_pack_progress", state.localPackProgress)
            .put("local_pack_storage_bytes", model.packManager.storageBytes())
            .put("offline_queue_depth", state.offlineQueueDepth)
            .put("offline_answering", state.offlineAnswering)
            .put("runtime_available", model.packManager.engine.isRuntimeAvailable())
            .put("engine", "llama.cpp")
            .put("packs", JSONArray(model.packManager.catalogJson()))
            .put("offline_banner_suggestion", CompanionOfflineStatus.offlineBannerText(state))
    }

    fun downloadPack(model: CompanionModel) = model.downloadCompanionPack()

    fun deletePack(model: CompanionModel) = model.deleteCompanionPack()

    fun selectPack(model: CompanionModel, packId: String) = model.selectCompanionPack(packId)

    fun refreshPackStatus(model: CompanionModel) = model.refreshCompanionPackStatus()
}
