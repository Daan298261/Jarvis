package com.jarvis.companion

/** A quick-answer preference cannot turn an explicit action into an answered question. */
object PhoneQuickMode {
    fun isQuestion(text: String): Boolean {
        val value = text.trim().lowercase(java.util.Locale.ROOT)
        if (Regex("^(please\\s+)?(open|launch|tap|click|send|delete|install|download|run|execute|enable|disable|schedule|stuur|verwijder|installeer|klik)\\b").containsMatchIn(value)) return false
        return StandaloneMode.classify(text, false, false).intent == StandaloneIntent.CONVERSATION
    }
}
