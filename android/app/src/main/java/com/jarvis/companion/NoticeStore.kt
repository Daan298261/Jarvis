package com.jarvis.companion

import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject

/** What a notice is about; maps to its localized title. Persisted by name, so never rename entries. */
enum class NoticeKind { DESKTOP_OFFLINE, PENDING_MESSAGE, MODEL_DOWNLOAD, VOICE_DOWNLOAD, ERROR }

enum class NoticeSeverity { INFO, WARNING, ERROR }

/** Buttons a notice can offer; the screen that hosts the list decides how to run each. */
enum class NoticeAction { RETRY_PENDING, DISCARD_PENDING, PAIR, SCAN_WIFI, RETRY_MODEL_DOWNLOAD, RETRY_VOICE_DOWNLOAD, OPEN_APP_SETTINGS }

/** A condition that holds right now (desktop unreachable, a download failed). It clears itself once resolved. */
data class LiveCondition(
    val kind: NoticeKind,
    val severity: NoticeSeverity,
    /** Dynamic detail text; null means the kind's standard body. */
    val body: String?,
    val actions: List<NoticeAction> = emptyList(),
) {
    val signature: String get() = "${severity.name}|${body.orEmpty()}"
}

data class Notice(
    val id: String,
    val kind: NoticeKind,
    val severity: NoticeSeverity,
    val body: String?,
    val timeMillis: Long,
    val live: Boolean,
    val read: Boolean,
    val actions: List<NoticeAction>,
)

/**
 * The one place every ANZU in-app notice goes through (status banners used to sit on top of Home).
 *
 * - Live conditions are re-derived from app state by [syncLive]; they update when their text changes and vanish
 *   when the condition resolves. Their first-seen time, read and dismissed state persist, so a restart does not
 *   re-raise something the user already read or dismissed.
 * - Events (errors) are dated, persisted, capped at [maxEvents] and dropped after [maxAgeMs].
 */
class NoticeStore(
    private val prefs: SharedPreferences,
    private val clock: () -> Long = System::currentTimeMillis,
    private val maxEvents: Int = 50,
    private val maxAgeMs: Long = 7L * 24 * 60 * 60 * 1000,
) {
    private class LiveEntry(val signature: String, val since: Long, var read: Boolean, var dismissed: Boolean)

    private val lock = Any()
    private val live = LinkedHashMap<NoticeKind, LiveEntry>()
    private var conditions: Map<NoticeKind, LiveCondition> = emptyMap()
    private val events = ArrayList<Notice>()
    private var seq = 0L
    private val flow = MutableStateFlow<List<Notice>>(emptyList())

    /** Visible notices, newest first. */
    val notices: StateFlow<List<Notice>> = flow.asStateFlow()

    init {
        synchronized(lock) {
            load()
            prune()
            publish()
        }
    }

    fun unreadCount(): Int = notices.value.count { !it.read }

    /** Replace the set of live conditions; anything not in [current] is resolved and removed. */
    fun syncLive(current: List<LiveCondition>) = synchronized(lock) {
        val next = current.associateBy { it.kind }
        if (next == conditions && live.keys == next.keys) return@synchronized
        live.keys.retainAll(next.keys)
        for ((kind, c) in next) {
            val entry = live[kind]
            if (entry == null || entry.signature != c.signature) {
                live[kind] = LiveEntry(c.signature, clock(), read = false, dismissed = false)
            }
        }
        conditions = next
        save()
        publish()
    }

    /** Record a dated event, e.g. an error the app reported. Identical repeats within 2 s are folded. */
    fun postEvent(kind: NoticeKind, severity: NoticeSeverity, body: String, actions: List<NoticeAction> = emptyList()) = synchronized(lock) {
        val now = clock()
        val last = events.firstOrNull()
        if (last != null && last.kind == kind && last.body == body && now - last.timeMillis < 2_000) return@synchronized
        events.add(0, Notice("evt-$now-${seq++}", kind, severity, body, now, live = false, read = false, actions = actions))
        prune()
        save()
        publish()
    }

    fun dismiss(id: String) = synchronized(lock) {
        if (!events.removeAll { it.id == id }) {
            liveKind(id)?.let { live[it]?.dismissed = true }
        }
        save()
        publish()
    }

    /** Remove every event and hide every live notice until its condition changes or recurs. */
    fun clearAll() = synchronized(lock) {
        events.clear()
        live.values.forEach { it.dismissed = true }
        save()
        publish()
    }

    fun markAllRead() = synchronized(lock) {
        if (flow.value.none { !it.read }) return@synchronized
        for (i in events.indices) events[i] = events[i].copy(read = true)
        live.values.forEach { it.read = true }
        save()
        publish()
    }

    private fun liveKind(id: String): NoticeKind? =
        id.removePrefix("live-").takeIf { id.startsWith("live-") }?.let { name -> NoticeKind.entries.firstOrNull { it.name == name } }

    private fun prune() {
        val cutoff = clock() - maxAgeMs
        events.removeAll { it.timeMillis < cutoff }
        while (events.size > maxEvents) events.removeAt(events.size - 1)
    }

    private fun publish() {
        val liveNotices = conditions.values.mapNotNull { c ->
            val e = live[c.kind] ?: return@mapNotNull null
            if (e.dismissed) null
            else Notice("live-${c.kind.name}", c.kind, c.severity, c.body, e.since, live = true, read = e.read, actions = c.actions)
        }
        flow.value = (liveNotices + events).sortedByDescending { it.timeMillis }
    }

    private fun save() {
        val liveJson = JSONObject()
        live.forEach { (kind, e) ->
            liveJson.put(kind.name, JSONObject().put("sig", e.signature).put("since", e.since).put("read", e.read).put("dismissed", e.dismissed))
        }
        val eventsJson = JSONArray()
        events.forEach { n ->
            eventsJson.put(JSONObject().put("id", n.id).put("kind", n.kind.name).put("severity", n.severity.name)
                .put("body", n.body.orEmpty()).put("time", n.timeMillis).put("read", n.read)
                .put("actions", JSONArray(n.actions.map { it.name })))
        }
        prefs.edit().putString(KEY_LIVE, liveJson.toString()).putString(KEY_EVENTS, eventsJson.toString()).apply()
    }

    private fun load() {
        runCatching {
            val liveJson = JSONObject(prefs.getString(KEY_LIVE, null) ?: "{}")
            for (name in liveJson.keys()) {
                val kind = NoticeKind.entries.firstOrNull { it.name == name } ?: continue
                val o = liveJson.getJSONObject(name)
                live[kind] = LiveEntry(o.getString("sig"), o.getLong("since"), o.optBoolean("read"), o.optBoolean("dismissed"))
            }
        }
        runCatching {
            val arr = JSONArray(prefs.getString(KEY_EVENTS, null) ?: "[]")
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val kind = NoticeKind.entries.firstOrNull { it.name == o.optString("kind") } ?: continue
                val severity = NoticeSeverity.entries.firstOrNull { it.name == o.optString("severity") } ?: NoticeSeverity.ERROR
                val actionsJson = o.optJSONArray("actions") ?: JSONArray()
                val actions = (0 until actionsJson.length()).mapNotNull { j -> NoticeAction.entries.firstOrNull { it.name == actionsJson.optString(j) } }
                events += Notice(o.getString("id"), kind, severity, o.optString("body"), o.getLong("time"), live = false, read = o.optBoolean("read"), actions = actions)
            }
            events.sortByDescending { it.timeMillis }
        }
    }

    companion object {
        const val PREFS = "anzu_notices"
        private const val KEY_LIVE = "live"
        private const val KEY_EVENTS = "events"
    }
}

/** Derives notices from [CompanionState]. Pure, so the rules are unit-tested without a ViewModel. */
object NoticeRules {
    fun conditions(state: CompanionState, paired: Boolean): List<LiveCondition> {
        val out = ArrayList<LiveCondition>()
        val offline = CompanionOfflineStatus.offlineBannerText(state)
        if (offline.isNotEmpty()) {
            val severity = if (state.localModelReady) NoticeSeverity.INFO else NoticeSeverity.WARNING
            out += LiveCondition(NoticeKind.DESKTOP_OFFLINE, severity, offline,
                listOf(if (paired) NoticeAction.SCAN_WIFI else NoticeAction.PAIR))
        }
        if (state.pendingMessage) {
            out += LiveCondition(NoticeKind.PENDING_MESSAGE, NoticeSeverity.WARNING, null,
                listOf(NoticeAction.RETRY_PENDING, NoticeAction.DISCARD_PENDING))
        }
        if (state.localPackError.isNotBlank() && state.localPackStatus != CompanionPackStatus.DOWNLOADING) {
            out += LiveCondition(NoticeKind.MODEL_DOWNLOAD, NoticeSeverity.ERROR, state.localPackError,
                listOf(NoticeAction.RETRY_MODEL_DOWNLOAD))
        }
        val voiceDownloading = state.voiceSttStatus == CompanionVoicePackStatus.DOWNLOADING ||
            state.voiceTtsStatus == CompanionVoicePackStatus.DOWNLOADING
        if (state.voicePackError.isNotBlank() && !voiceDownloading) {
            out += LiveCondition(NoticeKind.VOICE_DOWNLOAD, NoticeSeverity.ERROR, state.voicePackError,
                listOf(NoticeAction.RETRY_VOICE_DOWNLOAD))
        }
        return out
    }

    /** Actions offered with a reported error: a permission problem can only be fixed in system settings. */
    fun errorActions(message: String): List<NoticeAction> =
        if (message.contains("permission", ignoreCase = true)) listOf(NoticeAction.OPEN_APP_SETTINGS) else emptyList()
}
