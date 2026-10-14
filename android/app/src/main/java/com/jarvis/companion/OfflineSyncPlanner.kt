package com.jarvis.companion

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** One `/sync/offline-turns` request: the turns of a single conversation, in queue order. */
data class OfflineSyncBatch(
    /** The conversation key stored on the turns (a phone chat id, a desktop id, or "" for legacy turns). */
    val conversationKey: String,
    /** Desktop conversation already known for this batch; null means the phone must mint and persist one first. */
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
                key.isEmpty() || LocalConversationStore.isLocal(key) -> desktopIdFor(key)
                else -> key
            }
            turns.chunked(MAX_TURNS_PER_REQUEST).map { OfflineSyncBatch(key, desktop, it) }
        }
    }

    /** Wire form of a turn: the phone-only routing key is not sent to the desktop. */
    fun wireTurn(turn: JSONObject): JSONObject = JSONObject(turn.toString()).apply { remove(CONVERSATION_KEY) }

    fun turnId(turn: JSONObject): String = turn.optString("client_message_id").ifBlank { turn.optString("request_id") }

    fun newThreadId(): String = UUID.randomUUID().toString()

    /**
     * Desktop thread for [batch]: the one already known, or a new UUID that is persisted in [ids] BEFORE
     * any request is sent. A lost reply then retries into the same thread (the desktop dedupes turns per
     * thread by client_message_id) instead of opening a second one, and later batches of the same
     * conversation join it even if an earlier batch failed.
     */
    fun threadFor(batch: OfflineSyncBatch, ids: DesktopThreadIds, newId: () -> String = ::newThreadId): String {
        batch.desktopConversationId?.let { return it }
        ids.get(batch.conversationKey)?.let { return it }
        return newId().also { ids.put(batch.conversationKey, it) }
    }

    /**
     * Sends every pending turn, one request per conversation chunk, always naming the desktop thread.
     * [post] sends one request; a throw stops the run with the remaining turns still queued.
     * [synced] is told the turn ids a successful request delivered.
     */
    inline fun syncAll(
        pending: List<JSONObject>,
        ids: DesktopThreadIds,
        noinline newId: () -> String = ::newThreadId,
        post: (conversationId: String, turns: JSONArray) -> Unit,
        synced: (turnIds: List<String>) -> Unit,
    ) {
        for (batch in plan(pending) { ids.get(it) }) {
            val target = threadFor(batch, ids, newId)
            post(target, JSONArray().also { arr -> batch.turns.forEach { arr.put(wireTurn(it)) } })
            synced(batch.turns.map(::turnId))
        }
    }
}

/** Where the phone keeps the desktop thread id of each offline conversation key. */
interface DesktopThreadIds {
    fun get(conversationKey: String): String?
    fun put(conversationKey: String, desktopConversationId: String)
}

/**
 * Phone-persisted thread ids: a local conversation stores its link in [conversations]; turns without a
 * conversation (key "") and turns whose phone conversation was deleted use [prefs]. Writes are synchronous
 * so the id survives a crash between persisting and posting.
 */
class PhoneDesktopThreadIds(
    private val prefs: SharedPreferences,
    private val conversations: LocalConversationStore,
) : DesktopThreadIds {
    override fun get(conversationKey: String): String? {
        if (LocalConversationStore.isLocal(conversationKey)) {
            conversations.linkedDesktopId(conversationKey)?.let { return it }
        }
        return prefs.getString(prefKey(conversationKey), null)?.takeIf { it.isNotBlank() }
    }

    override fun put(conversationKey: String, desktopConversationId: String) {
        if (LocalConversationStore.isLocal(conversationKey) && conversations.linkDesktop(conversationKey, desktopConversationId)) return
        check(prefs.edit().putString(prefKey(conversationKey), desktopConversationId).commit()) {
            "Could not save the desktop thread for offline messages"
        }
    }

    private fun prefKey(conversationKey: String) = "offline_sync_thread:$conversationKey"
}
