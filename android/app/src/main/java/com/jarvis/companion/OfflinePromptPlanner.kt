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
    const val CLIPPED_NOTE =
        "Your last message was shortened because it was too long for one pass on this phone.\n\n"
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

    fun splitUntilTokenBudget(
        text: String,
        tokenize: (String) -> Int,
        promptBudget: Int,
    ): List<String> {
        val seedChars = ((promptBudget.coerceAtLeast(64)) * 4).coerceAtLeast(256)
        var sections = splitSections(text, seedChars)
        var i = 0
        var safety = 0
        while (i < sections.size && safety++ < 512) {
            val section = sections[i]
            val tokens = tokenize(summarizeSectionPrompt(section))
            if (tokens <= promptBudget || section.length <= 64) {
                i++
                continue
            }
            val parts = splitSections(section, (section.length / 2).coerceAtLeast(64))
            if (parts.size <= 1) {
                i++
                continue
            }
            sections = sections.take(i) + parts + sections.drop(i + 1)
        }
        return sections
    }

    fun trimHistory(
        history: List<JSONObject>,
        latest: String,
        tokenize: (String) -> Int,
        promptBudget: Int,
    ): List<JSONObject> {
        val cap = (promptBudget / 2).coerceAtLeast(64)
        var kept = history
        fun overBudget(): Boolean =
            tokenize(StandalonePrompt.build(kept, latest, pickedText = null)) > cap
        while (kept.size > 1 && overBudget()) {
            kept = kept.drop(1)
        }
        if (kept.size == 1 && overBudget()) {
            val only = kept[0]
            val isLatestUser = only.optString("role") == "user" && only.optString("text") == latest
            if (!isLatestUser) kept = emptyList()
        }
        return kept
    }

    /**
     * If the latest user turn alone (empty history) exceeds half the prompt budget,
     * shorten it so the skeleton fits. Returns the (possibly clipped) text and whether
     * a visible notice should be shown.
     */
    fun clipLatestToHalfBudget(
        latest: String,
        tokenize: (String) -> Int,
        promptBudget: Int,
    ): Pair<String, Boolean> {
        val cap = (promptBudget / 2).coerceAtLeast(64)
        fun tokens(text: String) = tokenize(StandalonePrompt.build(emptyList(), text, pickedText = null))
        if (latest.isEmpty() || tokens(latest) <= cap) return latest to false
        var lo = 0
        var hi = latest.length
        var best = ""
        while (lo <= hi) {
            val mid = (lo + hi) ushr 1
            val candidate = latest.substring(0, mid)
            if (tokens(candidate) <= cap) {
                best = candidate
                lo = mid + 1
            } else {
                hi = mid - 1
            }
        }
        val trimmed = best.trimEnd()
        val space = trimmed.lastIndexOf(' ')
        val wordCut = if (space >= 32) trimmed.substring(0, space).trimEnd() else trimmed
        val clipped = when {
            wordCut.isNotEmpty() && tokens(wordCut) <= cap -> wordCut
            trimmed.isNotEmpty() -> trimmed
            else -> latest.take(1)
        }
        return clipped to true
    }

    fun sectionSummaryMaxTokens(promptBudget: Int, skeletonTokens: Int, sectionCount: Int): Int =
        ((promptBudget - skeletonTokens) / sectionCount.coerceAtLeast(1)).coerceIn(32, 128)

    fun mergeAdjacent(summaries: List<String>): List<String> {
        if (summaries.size <= 1) return summaries
        val out = ArrayList<String>(summaries.size)
        var i = 0
        while (i < summaries.size) {
            if (i + 1 < summaries.size) {
                out.add(summaries[i] + "\n" + summaries[i + 1])
                i += 2
            } else {
                out.add(summaries[i])
                i++
            }
        }
        return out
    }

    data class Plan(
        val prompt: String,
        val sectioned: Boolean,
        val sections: List<String> = emptyList(),
        val history: List<JSONObject> = emptyList(),
        val skeletonTokens: Int = 0,
        val summaryMaxTokens: Int = 128,
        val latest: String = "",
        val clipped: Boolean = false,
    )

    fun plan(
        history: List<JSONObject>,
        latest: String,
        pickedText: String?,
        tokenize: (String) -> Int,
        promptBudget: Int,
    ): Plan {
        val (usedLatest, clipped) = clipLatestToHalfBudget(latest, tokenize, promptBudget)
        val trimmed = trimHistory(history, usedLatest, tokenize, promptBudget)
        val skeleton = StandalonePrompt.build(trimmed, usedLatest, pickedText = null)
        val skeletonTokens = tokenize(skeleton)
        val picked = pickedText?.takeIf { it.isNotBlank() }
        if (picked == null) {
            return Plan(
                prompt = skeleton,
                sectioned = false,
                history = trimmed,
                skeletonTokens = skeletonTokens,
                latest = usedLatest,
                clipped = clipped,
            )
        }
        val remaining = (promptBudget - skeletonTokens).coerceAtLeast(0)
        val pickedTokens = tokenize(picked)
        if (pickedTokens <= remaining && remaining > 0) {
            val full = StandalonePrompt.build(trimmed, usedLatest, picked)
            if (tokenize(full) <= promptBudget) {
                return Plan(
                    prompt = full,
                    sectioned = false,
                    history = trimmed,
                    skeletonTokens = skeletonTokens,
                    latest = usedLatest,
                    clipped = clipped,
                )
            }
        }
        val sections = splitUntilTokenBudget(picked, tokenize, promptBudget)
        return Plan(
            prompt = skeleton,
            sectioned = true,
            sections = sections,
            history = trimmed,
            skeletonTokens = skeletonTokens,
            summaryMaxTokens = sectionSummaryMaxTokens(promptBudget, skeletonTokens, sections.size),
            latest = usedLatest,
            clipped = clipped,
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
