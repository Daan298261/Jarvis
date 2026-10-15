package com.jarvis.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

@org.junit.runner.RunWith(org.robolectric.RobolectricTestRunner::class)
@org.robolectric.annotation.Config(sdk = [34])
class PhoneMemoryBudgetTest {
    private fun tokens(value: String) = (value.toByteArray().size + 3) / 4
    @Test fun completePromptFitsAndDoesNotRepeatNewestUserTurn() {
        val history = listOf(JSONObject().put("role", "user").put("text", "unique-latest-question"))
        val prompt = StandalonePrompt.build(history, "unique-latest-question")
        assertEquals(1, Regex("unique-latest-question").findAll(prompt).count())
        val memory = PhoneMemoryBudget.fit(JSONObject().put("owner_instructions", "Answer in Dutch").put("owner_notes", "note ".repeat(800))
            .put("historical_quotes", JSONArray().put(JSONObject().put("text", "old ".repeat(500)))).toString(), ::tokens, 200)
        assertTrue(tokens(memory) <= 200); assertTrue(memory.contains("Answer in Dutch"))
        val plan = OfflinePromptPlanner.plan(history, "unique-latest-question", null, ::tokens, 1400, memory)
        assertTrue(tokens(plan.prompt) <= 1400); assertTrue(plan.prompt.contains("Answer in Dutch"))
    }
    @Test fun sectionReductionKeepsMemoryAndNewestRequestInsideBudget() {
        val memory = JSONObject().put("owner_instructions", "Use metric units").toString()
        val prompt = OfflinePromptPlanner.boundedFinal(emptyList(), "newest request", listOf("source ".repeat(900)), memory, ::tokens, 500)
        assertTrue(tokens(prompt) <= 500); assertTrue(prompt.contains("newest request")); assertTrue(prompt.contains("Use metric units"))
    }
    @Test fun quickModelUsesSmallestInstalledPinnedModelAndNeverDownloads() {
        val packs = CompanionPackCatalog.builtIn
        val fast = CompanionPackCatalog.fastInstalledPack(packs) { it.id == CompanionPackCatalog.ABLITERATED_17B_ID || it.id == CompanionPackCatalog.ABLITERATED_06B_ID }
        assertEquals(CompanionPackCatalog.ABLITERATED_06B_ID, fast!!.id)
        assertNull(CompanionPackCatalog.fastInstalledPack(packs) { false })
        assertFalse(PhoneQuickMode.isQuestion("Open Chrome"))
        assertTrue(PhoneQuickMode.isQuestion("How do I open Chrome?"))
    }
}
