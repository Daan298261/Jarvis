package com.jarvis.companion

import org.json.JSONObject

/** One `/sync/offline-turns` request: the turns of a single conversation, in queue order. */
data class OfflineSyncBatch(
    /** The conversation key stored on the turns (a phone chat id, a desktop id, or "" for legacy turns). */
    val conversationKey: String,
    /** Desktop conversation to append to; null asks the desktop to start a new one. */
    val desktopConversationId: String?,
    val turns: List<JSONObject>,
)

/**
 * Groups queued offline turns by the conversation they were written in, so each lands in its own
 * desktop thread instead of whichever chat happens to be open when the desktop comes back.
 */
object OfflineSyncPlanner {
    const val CONVERSATION_KEY = "conversation_key"
    /** Matches `OfflineTurnSync.turns` max_length in backend/app/api/companion.py. */
    const val MAX_TURNS_PER_REQUEST = 50

    fun plan(pending: List<JSONObject>, desktopIdFor: (String) -> String?): List<OfflineSyncBatch> {
        val groups = LinkedHashMap<String, MutableList<JSONObject>>()
        pending.forEach { turn -> groups.getOrPut(turn.optString(CONVERSATION_KEY)) { mutableListOf() }.add(turn) }
        return groups.flatMap { (key, turns) ->
            val desktop = when {
                key.isEmpty() -> null
                LocalConversationStore.isLocal(key) -> desktopIdFor(key)
                else -> key
            }
            turns.chunked(MAX_TURNS_PER_REQUEST).map { OfflineSyncBatch(key, desktop, it) }
        }
    }

    /** Wire form of a turn: the phone-only routing key is not sent to the desktop. */
    fun wireTurn(turn: JSONObject): JSONObject = JSONObject(turn.toString()).apply { remove(CONVERSATION_KEY) }

    fun turnId(turn: JSONObject): String = turn.optString("client_message_id").ifBlank { turn.optString("request_id") }
}
