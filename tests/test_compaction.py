from __future__ import annotations

import sys
import unittest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.compaction import WORKING_MEMORY_MARK, compact_history, ensure_single_system, working_memory_text
from app.providers.base import ChatMessage


class CompactionTests(unittest.TestCase):
    def test_compact_does_not_insert_later_system_message(self) -> None:
        messages = [ChatMessage(role="system", content="You are Jarvis.")]
        messages.append(ChatMessage(role="user", content="fix the project"))
        for i in range(12):
            messages.append(ChatMessage(role="assistant", content="", tool_calls=[{"function": {"name": "filesystem"}}]))
            messages.append(ChatMessage(role="tool", name="filesystem", content=f"ok {i}"))
        compacted = compact_history(messages, keep_last=8)
        system_indexes = [i for i, message in enumerate(compacted) if message.role == "system"]
        self.assertEqual(system_indexes, [0])
        self.assertTrue(any(m.role == "user" and "Compacted" in str(m.content) for m in compacted))
        self.assertTrue(any("fix the project" in str(m.content) for m in compacted if m.role == "user"))

    def test_long_task_keeps_goal_failures_and_followups(self) -> None:
        goal = "Write TOKEN-T10-GOAL into C:\\Users\\daanv\\Desktop\\Jarvis-Test\\compact.txt and verify the file."
        messages = [
            ChatMessage(role="system", content="You are Jarvis."),
            ChatMessage(role="user", content=goal),
        ]
        for i in range(16):
            messages.append(
                ChatMessage(
                    role="assistant",
                    content="",
                    tool_calls=[{"id": f"c{i}", "function": {"name": "filesystem", "arguments": "{}"}}],
                )
            )
            if i == 4:
                messages.append(ChatMessage(role="tool", name="filesystem", content="ERROR: access is denied"))
            elif i == 6:
                messages.append(ChatMessage(role="tool", name="filesystem", content=f"listed directory noise {i}"))
                messages.append(ChatMessage(role="user", content="Follow-up: Append the word RESUMED. Do not lose TOKEN-T10-GOAL."))
                continue
            elif i == 8:
                messages.append(ChatMessage(role="tool", name="filesystem", content=f"Wrote C:\\Users\\daanv\\Desktop\\Jarvis-Test\\compact.txt ({i})"))
            else:
                messages.append(ChatMessage(role="tool", name="filesystem", content=f"listed directory noise {i} " * 20))
        compacted = compact_history(messages, keep_last=6, goal=goal)
        blob = "\n".join(str(m.content) for m in compacted)
        self.assertIn("TOKEN-T10-GOAL", blob)
        self.assertLess(len(blob), sum(len(str(m.content)) for m in messages))
        memory = next(m.content for m in compacted if m.role == "user" and WORKING_MEMORY_MARK in str(m.content))
        self.assertIn("TOKEN-T10-GOAL", memory)
        self.assertIn("denied", memory.lower())
        self.assertIn("RESUMED", memory)
        self.assertIn("Wrote", memory)
        self.assertEqual(compacted[1].content, goal)
        self.assertEqual(working_memory_text(messages), "")
        self.assertIn(WORKING_MEMORY_MARK, working_memory_text(compacted))
        roles = [m.role for m in compacted]
        for i, role in enumerate(roles):
            if role == "tool":
                self.assertEqual(roles[i - 1], "assistant")

    def test_repeated_noise_is_deduped_in_memory(self) -> None:
        messages = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="do the job")]
        for i in range(20):
            messages.append(ChatMessage(role="assistant", content="", tool_calls=[{"function": {"name": "filesystem"}}]))
            messages.append(ChatMessage(role="tool", name="filesystem", content="listed directory noise"))
        compacted = compact_history(messages, keep_last=4)
        memory = next(str(m.content) for m in compacted if m.role == "user" and WORKING_MEMORY_MARK in str(m.content))
        self.assertEqual(memory.count("listed directory noise"), 1)

    def test_ensure_single_system_rewrites_later_system(self) -> None:
        messages = [
            ChatMessage(role="system", content="root"),
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="system", content="later"),
        ]
        out = ensure_single_system(messages)
        self.assertEqual(out[0].role, "system")
        self.assertEqual(out[2].role, "user")
        self.assertEqual(out[2].content, "later")

    def test_compact_does_not_start_tail_on_tool_message(self) -> None:
        messages = [ChatMessage(role="system", content="You are Jarvis."), ChatMessage(role="user", content="do work")]
        for i in range(10):
            messages.append(ChatMessage(role="assistant", content="", tool_calls=[{"function": {"name": "filesystem"}}]))
            messages.append(ChatMessage(role="tool", name="filesystem", content=f"ok {i}"))
        compacted = compact_history(messages, keep_last=7)
        roles = [m.role for m in compacted]
        for i, role in enumerate(roles):
            if role == "tool":
                self.assertGreater(i, 0)
                self.assertEqual(roles[i - 1], "assistant")


if __name__ == "__main__":
    unittest.main()
