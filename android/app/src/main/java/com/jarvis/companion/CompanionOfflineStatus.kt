package com.jarvis.companion

import org.json.JSONObject

/**
 * UX hooks for Models screen + offline banner (RFC-0108). Wire from Compose without touching routing internals.
 */
object CompanionOfflineStatus {
    fun snapshot(state: CompanionState, packManager: CompanionPackManager): JSONObject {
        val routing = CompanionRouting.decide(
            leaderReachable = state.leaderReachable,
            packStatus = state.localPackStatus,
            resourceBlocked = state.localPackError.takeIf { it.isNotBlank() },
            hasStalePendingOnlineOutbox = state.pendingMessage,
        )
        return JSONObject()
            .put("leader_reachable", state.leaderReachable)
            .put("routing_mode", routing.mode.name)
            .put("routing_reason", routing.reason)
            .put("local_pack_status", state.localPackStatus)
            .put("local_pack_id", packManager.selectedPackId())
            .put("local_pack_progress", state.localPackProgress)
            .put("local_pack_storage_bytes", packManager.storageBytes())
            .put("offline_queue_depth", state.offlineQueueDepth)
            .put("offline_banner", offlineBannerText(state))
            .put("engine", "llama.cpp")
    }

    fun offlineBannerText(state: CompanionState): String = when {
        state.leaderReachable -> ""
        state.localPackStatus == "missing" -> "Leader unreachable — install a companion model pack to chat on-device"
        state.localPackStatus == "downloading" -> "Leader unreachable — downloading companion model (${state.localPackProgress}%)"
        state.localPackStatus in setOf("ready", "running") -> "Leader unreachable — answering on-device"
        else -> "Leader unreachable — ${state.localPackError.ifBlank { "companion model unavailable" }}"
    }
}
