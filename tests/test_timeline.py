from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.timeline import build_timeline, parse_command_output, serialize_tool_call


class ParseCommandOutputTests(unittest.TestCase):
    def test_splits_stdout_stderr_exit_and_duration(self) -> None:
        text = (
            "exit_code=1\n"
            "duration_ms=42.5\n"
            "--- stdout ---\n"
            "hello\n"
            "--- stderr ---\n"
            "boom\n"
        )
        parsed = parse_command_output(text)
        self.assertEqual(parsed["exit_code"], 1)
        self.assertEqual(parsed["duration_ms"], 42.5)
        self.assertEqual(parsed["stdout"], "hello")
        self.assertEqual(parsed["stderr"], "boom")

    def test_plain_output_is_stdout(self) -> None:
        parsed = parse_command_output("wrote notes.txt")
        self.assertEqual(parsed["stdout"], "wrote notes.txt")
        self.assertEqual(parsed["stderr"], "")
        self.assertIsNone(parsed["exit_code"])


class TimelineMergeTests(unittest.TestCase):
    def test_tool_event_gets_expandable_io(self) -> None:
        events = [
            SimpleNamespace(kind="stage", title="Understanding the request", detail="", stage="understand", created_at=None),
            SimpleNamespace(kind="tool", title="Running terminal", detail='{"command": "echo hi"}', stage="act", created_at=None),
            SimpleNamespace(kind="observation", title="terminal finished", detail="ok", stage="observe", created_at=None),
        ]
        calls = [
            SimpleNamespace(
                tool_name="terminal",
                arguments_json='{"command": "echo hi"}',
                output="exit_code=0\nduration_ms=12\n--- stdout ---\nhi\n--- stderr ---\n",
                success=True,
                error="",
                duration_ms=12,
            )
        ]
        steps = build_timeline(events, calls)
        tool_step = next(item for item in steps if item["kind"] == "tool")
        self.assertTrue(tool_step["expandable"])
        self.assertEqual(tool_step["backend"], "terminal")
        self.assertEqual(tool_step["stdout"], "hi")
        self.assertEqual(tool_step["exit_code"], 0)
        self.assertEqual(tool_step["duration_ms"], 12)

    def test_two_tool_events_each_get_io(self) -> None:
        events = [
            SimpleNamespace(kind="tool", title="Running filesystem", detail="", stage="act", created_at=None),
            SimpleNamespace(kind="observation", title="filesystem finished", detail="ok", stage="observe", created_at=None),
            SimpleNamespace(kind="tool", title="Running filesystem", detail="", stage="act", created_at=None),
        ]
        calls = [
            SimpleNamespace(tool_name="filesystem", arguments_json='{"action":"mkdir"}', output="created dir", success=True, error="", duration_ms=1),
            SimpleNamespace(tool_name="filesystem", arguments_json='{"action":"write"}', output="wrote file", success=True, error="", duration_ms=2),
        ]
        steps = build_timeline(events, calls)
        tools = [item for item in steps if item["kind"] == "tool"]
        self.assertEqual(len(tools), 2)
        self.assertTrue(all(item["expandable"] for item in tools))
        self.assertEqual(tools[0]["stdout"], "created dir")
        self.assertEqual(tools[1]["stdout"], "wrote file")
        observation = next(item for item in steps if item["kind"] == "observation")
        self.assertFalse(observation.get("expandable"))

    def test_hides_chain_of_thought_events(self) -> None:
        events = [
            SimpleNamespace(kind="model", title="Model is thinking", detail="secret plan", stage="act", created_at=None),
            SimpleNamespace(kind="progress", title="Reasoning complete", detail="<think>hidden</think>", stage="act", created_at=None),
            SimpleNamespace(kind="tool", title="Running filesystem", detail="", stage="act", created_at=None),
        ]
        calls = [
            SimpleNamespace(
                tool_name="filesystem",
                arguments_json='{"path": "notes.txt"}',
                output="wrote notes.txt",
                success=True,
                error="",
                duration_ms=8,
            )
        ]
        steps = build_timeline(events, calls)
        titles = [item["title"] for item in steps]
        self.assertNotIn("Model is thinking", titles)
        self.assertNotIn("Reasoning complete", titles)
        self.assertEqual(titles, ["Running filesystem"])
        self.assertNotIn("secret plan", str(steps))
        self.assertNotIn("<think>", str(steps))

    def test_unmatched_tool_calls_are_appended(self) -> None:
        events = [SimpleNamespace(kind="stage", title="Understanding the request", detail="", stage="understand", created_at=None)]
        calls = [
            SimpleNamespace(
                tool_name="python",
                arguments_json='{"code": "print(1)"}',
                output="exit_code=0\n--- stdout ---\n1\n",
                success=True,
                error="",
                duration_ms=5,
            )
        ]
        steps = build_timeline(events, calls)
        tool_step = next(item for item in steps if item.get("expandable"))
        self.assertEqual(tool_step["backend"], "python")
        self.assertEqual(tool_step["stdout"], "1")
        self.assertEqual(tool_step["exit_code"], 0)

    def test_serialize_uses_record_error_as_stderr_fallback(self) -> None:
        row = SimpleNamespace(
            tool_name="filesystem",
            arguments_json="{}",
            output="denied",
            success=False,
            error="not allowed",
            duration_ms=3,
        )
        payload = serialize_tool_call(row)
        self.assertEqual(payload["stderr"], "not allowed")
        self.assertFalse(payload["success"])


class FrontendTimelineTests(unittest.TestCase):
    def test_chat_page_has_expandable_tool_details(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "Chat.tsx").read_text(encoding="utf-8")
        self.assertIn("timeline", source)
        self.assertIn("expandable", source)
        self.assertIn("stdout", source)
        self.assertIn("stderr", source)
        self.assertIn("exit_code", source)
        self.assertIn("duration_ms", source)
        self.assertNotIn("chain-of-thought", source.lower())
        self.assertIn("isHiddenThought", source)
        self.assertIn("reasoning complete", source.lower())


class AgentDoesNotPublishThoughtTests(unittest.TestCase):
    def test_loop_does_not_publish_reasoning_text(self) -> None:
        source = (ROOT / "backend" / "app" / "agent" / "loop.py").read_text(encoding="utf-8")
        self.assertNotIn("Reasoning complete", source)
        self.assertNotIn("result.reasoning[-1500:]", source)


if __name__ == "__main__":
    unittest.main()
