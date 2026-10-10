package com.jarvis.companion

import org.json.JSONObject

/**
 * On-device system prompt for Black Grid mode (RFC-0204 §1.1).
 * Identifies ANZU on this phone. Does not invent desktop tool results.
 */
object StandalonePrompt {
    const val PICKED_TEXT_BUDGET_BYTES = 64 * 1024

    fun build(
        history: List<JSONObject>,
        latest: String,
        pickedText: String? = null,
    ): String {
        val lines = history.takeLast(12).map { "${it.optString("role")}: ${it.optString("text")}" }
        val context = if (lines.isEmpty()) "" else lines.joinToString("\n") + "\n"
        val excerpt = pickedText?.takeIf { it.isNotBlank() }?.let { raw ->
            val clipped = clipToBudget(raw)
            "\nOwner-picked text (use this as source material):\n$clipped\n"
        } ?: ""
        return """
You are ANZU on this phone. The ANZU desktop is unreachable.
Answer from the conversation, general knowledge, and any owner-picked text below.
Do not claim to run desktop tools, HexStrike, filesystem access on the PC, Black Grid media studio, or swarm workers.
Spoken replies must stay speakable: do not read code, URLs, or internal status aloud.
$excerpt
$context
user: $latest
assistant:
        """.trimIndent()
    }

    fun clipToBudget(text: String): String {
        val bytes = text.toByteArray(Charsets.UTF_8)
        if (bytes.size <= PICKED_TEXT_BUDGET_BYTES) return text
        return String(bytes.copyOfRange(0, PICKED_TEXT_BUDGET_BYTES), Charsets.UTF_8)
    }

    fun identifiesAnzu(prompt: String): Boolean =
        prompt.contains("ANZU on this phone") &&
            prompt.contains("ANZU desktop is unreachable") &&
            !prompt.contains("Leader") &&
            !Regex("""\bJarvis\b""").containsMatchIn(prompt)
}
