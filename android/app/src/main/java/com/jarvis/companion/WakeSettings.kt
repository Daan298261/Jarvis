package com.jarvis.companion

import android.content.Context
import java.util.Locale

class WakeSettings(context: Context) {
    private val prefs = context.getSharedPreferences("anzu_assistant", Context.MODE_PRIVATE)
    var enabled: Boolean
        get() = prefs.getBoolean("wake_enabled", false)
        set(value) { prefs.edit().putBoolean("wake_enabled", value).apply() }
    var phrases: String
        get() = prefs.getString("wake_phrases", DEFAULT_PHRASES) ?: DEFAULT_PHRASES
        set(value) { prefs.edit().putString("wake_phrases", value).apply() }
    var threshold: Float
        get() = prefs.getFloat("wake_threshold", 0.15f).let { if (it.isFinite()) it.coerceIn(0.05f, 0.6f) else 0.15f }
        set(value) { require(value.isFinite()); prefs.edit().putFloat("wake_threshold", value.coerceIn(0.05f, 0.6f)).apply() }
    var screenContext: Boolean
        get() = prefs.getBoolean("screen_context", false)
        set(value) { prefs.edit().putBoolean("screen_context", value).apply() }

    fun keywords(context: Context, phrases: String = this.phrases): String {
        val dictionary = context.assets.open("wake/en.phone").bufferedReader().useLines { lines ->
            lines.mapNotNull { line ->
                val parts = line.trim().split(Regex("\\s+"), limit = 2)
                if (parts.size == 2) parts[0] to parts[1] else null
            }.toMap()
        }
        val tokens = context.assets.open("wake/tokens.txt").bufferedReader().useLines { lines -> lines.map { it.substringBefore(' ') }.toSet() }
        return compile(phrases, dictionary, tokens)
    }

    companion object {
        const val DEFAULT_PHRASES = "hey anzu, hey anu, hey jarvis, hey anoe, hey enzo, hey anzoo, hey aanzo, jarvis, anzu, anoe, enzo, anzoo, aanzo"
        private val aliases = mapOf(
            "ANZU" to "AE1 N Z UW1", "ANU" to "AA1 N UW1", "ANOE" to "AA1 N UW1",
            "ENZO" to "EH1 N Z OW0", "ANZOO" to "AE1 N Z UW1", "AANZO" to "AA1 N Z OW0",
            "JARVIS" to "JH AA1 R V AH0 S",
        )
        fun compile(text: String, dictionary: Map<String, String>, tokens: Set<String>): String {
            val phrases = text.split(',', '\n').map { it.trim().uppercase(Locale.ROOT) }.filter { it.isNotEmpty() }.distinct()
            require(phrases.isNotEmpty() && phrases.size <= 20) { "Enter 1 to 20 wake phrases, separated by commas." }
            return phrases.joinToString("\n") { phrase ->
                require(phrase.matches(Regex("[A-Z]+(?: [A-Z]+){0,3}"))) { "Use up to four English words per wake phrase." }
                val phones = phrase.split(' ').map { word -> aliases[word] ?: dictionary[word] ?: error("No pronunciation for $word. Try ANZU, Anoe, Enzo or Jarvis.") }.joinToString(" ")
                require(phones.split(' ').all { it in tokens }) { "This wake phrase uses unsupported sounds: $phrase" }
                "$phones @${phrase.replace(' ', '_')}"
            } + "\n"
        }
    }
}
