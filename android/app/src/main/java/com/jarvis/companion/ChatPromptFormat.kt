package com.jarvis.companion

/**
 * Chat-template wrapping for on-device packs (RFC-0204). Every catalog pack is a Qwen
 * ChatML model; raw "user:/assistant:" completion prompts make instruct models ramble
 * and let Qwen3.5 open a long hidden <think> block. Qwen3.5 gets an empty think block
 * prefilled so it answers directly within the phone's small token budget.
 */
object ChatPromptFormat {
    enum class Style { RAW, CHATML, CHATML_NO_THINK }

    fun styleFor(modelPath: String): Style {
        val name = modelPath.substringAfterLast('/').substringAfterLast('\\').lowercase()
        return when {
            Regex("""qwen3[._]?5""").containsMatchIn(name) -> Style.CHATML_NO_THINK
            name.contains("qwen") -> Style.CHATML
            else -> Style.RAW
        }
    }

    fun wrap(prompt: String, style: Style): String {
        if (style == Style.RAW) return prompt
        val body = prompt.trimEnd().removeSuffix("assistant:").trimEnd()
        val head = "<|im_start|>user\n$body<|im_end|>\n<|im_start|>assistant\n"
        return if (style == Style.CHATML_NO_THINK) "$head<think>\n\n</think>\n\n" else head
    }

    private val thinkBlock = Regex("""<think>[\s\S]*?(</think>|$)""")

    /** Drop any reasoning block or template marker that leaks into the visible reply. */
    fun clean(output: String, style: Style): String {
        if (style == Style.RAW) return output
        return output.replace(thinkBlock, "").replace("<|im_end|>", "").trimStart()
    }
}
