package com.jarvis.companion

import org.junit.Assert.*
import org.junit.Test

class LiveLocalReplyTest {
    @Test fun publishesFirstTokenBeforeCompletionAndCoalescesLaterTokens() {
        var clock = 0L
        val seen = mutableListOf<String>()
        val reply = LiveLocalReply({ clock }, seen::add)
        reply.append("Hello")
        assertEquals(listOf("Hello"), seen)
        reply.append(" there")
        assertEquals(1, seen.size)
        clock = 80
        reply.append("!")
        assertEquals(listOf("Hello", "Hello there!"), seen)
        reply.append(" More.")
        assertEquals("Hello there! More.", reply.text())
    }

    @Test fun splitReasoningAndTemplateMarkersNeverLeak() {
        val seen = mutableListOf<String>()
        val reply = LiveLocalReply({ 100L }, seen::add)
        reply.append("<th")
        reply.append("ink>secret")
        assertTrue(seen.isEmpty())
        reply.append("</think>Answer")
        assertEquals(listOf("Answer"), seen)
        reply.append("<|im_")
        assertEquals("Answer", reply.text())
        reply.append("end|>")
        assertEquals("Answer", reply.text())
    }
}
