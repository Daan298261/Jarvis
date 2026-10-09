package com.jarvis.companion

import org.json.JSONObject

/**
 * Token budget, prompt batching, and map-reduce for on-device GGUF turns (RFC-0204).
 */
object OfflinePromptPlanner {
    const val N_BATCH = 512
    const val N_CTX_MIN = 2048
    const val N_CTX_MAX = 4096
    const val SECTIONED_NOTE =
        "I summarized the picked text in sections because it was too long for one pass on this phone.\n\n"
    const val TRUNCATED_NOTE =
        "\n\n(Answer truncated — reached the on-device context or length limit.)"

    fun promptTokenBudget(nCtx: Int, answerTokens: Int): Int =
        (nCtx - answerTokens - 32).coerceAtLeast(128)

    fun promptBatches(tokenCount: Int, batchSize: Int = N_BATCH): List<Int> {
        if (tokenCount <= 0) return emptyList()
        val out = ArrayList<Int>()
        var left = tokenCount
        while (left > 0) {
            val n = minOf(batchSize, left)
            out.add(n)
            left -= n
        }
        return out
    }

    fun splitSections(text: String, maxChars: Int): List<String> {
        val clipped = text.trim()
        if (clipped.isEmpty()) return emptyList()
        val limit = maxChars.coerceAtLeast(64)
        if (clipped.length <= limit) return listOf(clipped)
        val out = ArrayList<String>()
        var rest = clipped
        while (rest.length > limit) {
            val cut = rest.lastIndexOf(' ', limit).let { if (it < 32) limit else it }
            out.add(rest.substring(0, cut).trim())
            rest = rest.substring(cut).trim()
        }
        if (rest.isNotEmpty()) out.add(rest)
        return out
    }

    data class Plan(
        val prompt: String,
        val sectioned: Boolean,
        val sections: List<String> = emptyList(),
    )

    fun plan(
        history: List<JSONObject>,
        latest: String,
        pickedText: String?,
        tokenize: (String) -> Int,
        promptBudget: Int,
    ): Plan {
        val skeleton = StandalonePrompt.build(history, latest, pickedText = null)
        val skeletonTokens = tokenize(skeleton)
        val picked = pickedText?.takeIf { it.isNotBlank() }
        if (picked == null) {
            return Plan(prompt = skeleton, sectioned = false)
        }
        val remaining = (promptBudget - skeletonTokens).coerceAtLeast(0)
        val pickedTokens = tokenize(picked)
        if (pickedTokens <= remaining && remaining > 0) {
            return Plan(prompt = StandalonePrompt.build(history, latest, picked), sectioned = false)
        }
        val sectionChars = ((remaining.coerceAtLeast(64)) * 4).coerceAtLeast(256)
        val sections = splitSections(picked, sectionChars)
        return Plan(
            prompt = StandalonePrompt.build(history, latest, pickedText = null),
            sectioned = true,
            sections = sections,
        )
    }

    fun summarizeSectionPrompt(section: String): String =
        "You are ANZU on this phone. Summarize this section of owner-picked text in a few sentences. Keep facts. Do not answer a user question yet.\n\n$section\n\nsummary:"

    fun finalPromptFromSummaries(
        history: List<JSONObject>,
        latest: String,
        summaries: List<String>,
    ): String {
        val combined = summaries.mapIndexed { i, s -> "Section ${i + 1}: $s" }.joinToString("\n")
        return StandalonePrompt.build(history, latest, combined)
    }
}
