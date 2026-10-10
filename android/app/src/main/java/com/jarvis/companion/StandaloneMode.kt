package com.jarvis.companion

import org.json.JSONObject
import java.time.ZonedDateTime
import java.util.Locale

/**
 * Black Grid mode intent classification (RFC-0204 §1.1).
 * Deterministic handling runs before the on-device model.
 */
enum class StandaloneIntent {
    CONVERSATION,
    LOCAL_REMINDER,
    REMINDER_NEEDS_TIME,
    LOCAL_NOTE,
    LOCAL_FILE,
    MEDIA_WAIT_DESKTOP,
    QUEUE_OR_REFUSE,
}

data class StandaloneDecision(
    val intent: StandaloneIntent,
    val reminderAt: ZonedDateTime? = null,
    val consequential: Boolean = false,
    val autoReplay: Boolean = true,
)

object StandaloneMode {
    private val reminderCue = Regex(
        """\b(remind\s+me|set\s+(an?\s+)?(reminder|alarm)|notify\s+me|wake\s+me)\b""",
        RegexOption.IGNORE_CASE,
    )
    private val noteCue = Regex(
        """\b(remember\s+this|take\s+a\s+note|make\s+a\s+note|save\s+this|note:|don'?t\s+forget)\b""",
        RegexOption.IGNORE_CASE,
    )
    private val desktopOnly = Regex(
        """\b(send\s+(an?\s+)?email|email\s+this|mail\s+this|whatsapp|send\s+(this\s+)?(message|sms|text)|hexstrike|run\s+hexstrike|generate\s+(an?\s+)?(image|video)|make\s+(me\s+)?(an?\s+)?(image|video)|draw\s+me|black\s*grid\s+studio|studio\s+render|edit\s+(the\s+)?files?\s+on\s+(the\s+)?(pc|desktop|computer)|(open|use)\s+(the\s+)?desktop\s+browser|browse\s+on\s+(the\s+)?(pc|desktop)|run.{0,40}\b(terminal|powershell|cmd)\b|open.{0,40}\b(terminal|powershell|cmd)\b|(word|excel|powerpoint|office)\s+on\s+(the\s+)?(pc|desktop)|swarm|spawn\s+workers?)\b""",
        RegexOption.IGNORE_CASE,
    )
    private val consequentialCue = Regex(
        """\b(send\s+(an?\s+)?email|email\s+this|whatsapp|send\s+(this\s+)?(message|sms|text)|pay|transfer\s+money|delete|hexstrike|security\s+scan|wipe)\b""",
        RegexOption.IGNORE_CASE,
    )

    fun classify(
        text: String,
        hasPickedText: Boolean = false,
        hasMediaAttachment: Boolean = false,
        now: ZonedDateTime = ZonedDateTime.now(),
    ): StandaloneDecision {
        val trimmed = text.trim()
        if (hasMediaAttachment) {
            return StandaloneDecision(
                intent = StandaloneIntent.MEDIA_WAIT_DESKTOP,
                consequential = false,
                autoReplay = false,
            )
        }
        if (hasPickedText) {
            return StandaloneDecision(intent = StandaloneIntent.LOCAL_FILE, autoReplay = true)
        }
        if (reminderCue.containsMatchIn(trimmed)) {
            val at = StandaloneActions.parseReminderInstant(trimmed, now)
            return if (at != null) {
                StandaloneDecision(intent = StandaloneIntent.LOCAL_REMINDER, reminderAt = at, autoReplay = true)
            } else {
                StandaloneDecision(intent = StandaloneIntent.REMINDER_NEEDS_TIME, autoReplay = true)
            }
        }
        if (desktopOnly.containsMatchIn(trimmed)) {
            val consequential = consequentialCue.containsMatchIn(trimmed)
            return StandaloneDecision(
                intent = StandaloneIntent.QUEUE_OR_REFUSE,
                consequential = consequential,
                autoReplay = !consequential,
            )
        }
        if (noteCue.containsMatchIn(trimmed)) {
            return StandaloneDecision(intent = StandaloneIntent.LOCAL_NOTE, autoReplay = true)
        }
        return StandaloneDecision(intent = StandaloneIntent.CONVERSATION, autoReplay = true)
    }

    fun shouldSpeakVoiceReply(fromVoice: Boolean, ttsRoute: TtsVoiceRoute): Boolean =
        fromVoice && ttsRoute == TtsVoiceRoute.ON_DEVICE

    fun desktopOnlyNeverDone(decision: StandaloneDecision): Boolean =
        decision.intent == StandaloneIntent.QUEUE_OR_REFUSE ||
            decision.intent == StandaloneIntent.MEDIA_WAIT_DESKTOP

    fun shouldAutoReplay(turn: JSONObject): Boolean {
        if (turn.optBoolean("synced", false)) return false
        if (turn.optBoolean("consequential", false)) return false
        if (!turn.optBoolean("auto_replay", true)) return false
        val origin = turn.optString("origin")
        return origin == StandaloneActions.ORIGIN_USER || origin == StandaloneActions.ORIGIN_ASSISTANT
    }
}
