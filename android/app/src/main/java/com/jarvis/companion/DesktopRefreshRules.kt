package com.jarvis.companion

import org.json.JSONObject

/**
 * What a desktop poll (`CompanionModel.refresh`) may change on Home and in Chat. While an on-device
 * reply is being written ([CompanionState.offlineAnswering]) the stage ticker owns `activity` and the
 * streamed bubble owns `messages`, so the poll leaves both alone (RFC-0235, criterion B).
 */
internal object DesktopRefreshRules {
    fun activity(state: CompanionState, voiceTaskActive: Boolean, desktopActivity: String?): String = when {
        state.offlineAnswering -> state.activity
        state.recording -> "Listening…"
        state.speaking -> state.activity
        voiceTaskActive -> "Desktop is processing your request…"
        else -> desktopActivity ?: "Ready when you are"
    }

    fun messages(state: CompanionState, conversationIdBeforePoll: String?, fetched: List<JSONObject>): List<JSONObject> =
        if (!state.offlineAnswering && state.conversationId == conversationIdBeforePoll) fetched else state.messages
}
