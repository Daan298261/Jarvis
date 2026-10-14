package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatPromptFormatTest {
    @Test
    fun styleFollowsPackFilename() {
        assertEquals(ChatPromptFormat.Style.CHATML_NO_THINK, ChatPromptFormat.styleFor("/data/model-packs/Qwen3.5-2B-heretic-Q4_K_M.gguf"))
        assertEquals(ChatPromptFormat.Style.CHATML_NO_THINK, ChatPromptFormat.styleFor("/x/Qwen3.5-4B-abliterated.Q4_K_M.gguf"))
        assertEquals(ChatPromptFormat.Style.CHATML, ChatPromptFormat.styleFor("/x/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"))
        assertEquals(ChatPromptFormat.Style.RAW, ChatPromptFormat.styleFor("/x/other.gguf"))
    }

    @Test
    fun wrapsPlannerPromptAsSingleUserTurn() {
        val wrapped = ChatPromptFormat.wrap("You are ANZU.\nuser: hi\nassistant:", ChatPromptFormat.Style.CHATML_NO_THINK)
        assertEquals(
            "<|im_start|>user\nYou are ANZU.\nuser: hi<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
            wrapped,
        )
        assertTrue(ChatPromptFormat.wrap("x", ChatPromptFormat.Style.CHATML).endsWith("<|im_start|>assistant\n"))
        assertEquals("raw", ChatPromptFormat.wrap("raw", ChatPromptFormat.Style.RAW))
    }

    @Test
    fun cleanStripsLeakedReasoning() {
        assertEquals("Answer.", ChatPromptFormat.clean("<think>plan</think>\nAnswer.<|im_end|>", ChatPromptFormat.Style.CHATML_NO_THINK))
        assertEquals("", ChatPromptFormat.clean("<think>never closed", ChatPromptFormat.Style.CHATML_NO_THINK))
    }
}
