package com.jarvis.companion

/** Coalesces native token callbacks without waiting for the complete answer. */
class LiveLocalReply(private val clockMs: () -> Long, private val publish: (String) -> Unit) {
    private val output = StringBuilder()
    private var lastPublish = Long.MIN_VALUE

    fun append(chunk: String) {
        output.append(chunk)
        val now = clockMs()
        if (lastPublish == Long.MIN_VALUE || now - lastPublish >= 80) {
            val visible = text()
            if (visible.isNotBlank()) { publish(visible); lastPublish = now }
        }
    }

    fun text(): String {
        val raw = output.toString()
        val lastTag = raw.lastIndexOf('<')
        val safe = if (lastTag >= 0 && !raw.substring(lastTag).contains('>')) raw.substring(0, lastTag) else raw
        return ChatPromptFormat.clean(safe, ChatPromptFormat.Style.CHATML_NO_THINK)
    }
}
