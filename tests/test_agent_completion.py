from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.completion import CompletionTracker, classify  # noqa: E402


class CompletionTrackerTests(unittest.TestCase):
    def test_write_then_read_same_path_completes(self) -> None:
        tracker = CompletionTracker()
        path = r"C:\Users\daanv\Desktop\Jarvis-Test\smoke.txt"
        tracker.record("filesystem", {"action": "mkdir", "path": r"C:\Users\daanv\Desktop\Jarvis-Test"}, True, "Created directory")
        tracker.record("filesystem", {"action": "write", "path": path}, True, f"Wrote {path} (6 bytes)")
        self.assertFalse(tracker.should_complete())
        tracker.record("filesystem", {"action": "read", "path": path}, True, "READY")
        self.assertTrue(tracker.should_complete())
        self.assertIn("smoke.txt", tracker.reason)
        report = tracker.synthesize_report("Create smoke.txt containing READY")
        self.assertIn("READY", report)
        self.assertIn("Wrote", report)

    def test_write_then_list_poll_completes(self) -> None:
        tracker = CompletionTracker()
        folder = r"C:\Users\daanv\Desktop\Jarvis-Test"
        tracker.record("filesystem", {"action": "write", "path": folder + r"\smoke.txt"}, True, "Wrote file")
        tracker.record("filesystem", {"action": "list", "path": folder}, True, "smoke.txt")
        self.assertFalse(tracker.should_complete())
        tracker.record("filesystem", {"action": "list", "path": folder}, True, "smoke.txt")
        self.assertTrue(tracker.should_complete())
        self.assertIn("poll", tracker.reason.lower())

    def test_inspect_only_does_not_complete_early(self) -> None:
        tracker = CompletionTracker()
        tracker.record("filesystem", {"action": "list", "path": r"C:\Users\daanv\Desktop"}, True, "files")
        tracker.record("filesystem", {"action": "read", "path": r"C:\Users\daanv\Desktop\a.txt"}, True, "hello")
        self.assertFalse(tracker.should_complete())

    def test_blocked_retry_after_write_completes(self) -> None:
        tracker = CompletionTracker()
        path = r"C:\Users\daanv\Desktop\Jarvis-Test\smoke.txt"
        tracker.record("filesystem", {"action": "write", "path": path}, True, "Wrote file")
        tracker.record("filesystem", {"action": "write", "path": path}, False, "blocked", blocked=True)
        self.assertTrue(tracker.should_complete())

    def test_mkdir_then_list_does_not_complete_before_write(self) -> None:
        tracker = CompletionTracker()
        folder = r"C:\Users\daanv\Desktop\Jarvis-Test"
        tracker.record("filesystem", {"action": "mkdir", "path": folder}, True, "Created directory")
        tracker.record("filesystem", {"action": "list", "path": folder}, True, "(empty)")
        tracker.record("filesystem", {"action": "list", "path": folder}, True, "(empty)")
        self.assertFalse(tracker.should_complete())

    def test_browser_save_title_counts_as_written_file(self) -> None:
        tracker = CompletionTracker()
        path = r"C:\Users\daanv\Desktop\Jarvis-Test\page-title.txt"
        tracker.record(
            "browser",
            {"action": "save_title", "url": "https://example.com", "path": path},
            True,
            f"Wrote title 'Example Domain' to {path}",
        )
        self.assertIn(path, tracker.written_paths())
        self.assertTrue(tracker.artifact_mutates())

    def test_desktop_write_counts_as_written_file(self) -> None:
        tracker = CompletionTracker()
        path = r"C:\Users\daanv\Desktop\Jarvis-Test\notepad-e2e.txt"
        tracker.record(
            "desktop",
            {"action": "write", "path": path, "text": "JARVIS-DESKTOP-E2E"},
            True,
            f"Wrote {path} via Notepad UI Automation",
        )
        self.assertIn(path, tracker.written_paths())
        self.assertTrue(tracker.artifact_mutates())

    def test_desktop_window_list_is_inspect_not_mutate(self) -> None:
        self.assertEqual(classify("desktop", "windows"), "inspect")
        self.assertEqual(classify("desktop", "apps"), "inspect")
        self.assertEqual(classify("desktop", "screenshot"), "inspect")
        self.assertEqual(classify("desktop", "focus"), "inspect")
        self.assertEqual(classify("desktop", "write"), "mutate")
        self.assertEqual(classify("desktop", "type"), "mutate")
        self.assertEqual(classify("desktop", "launch"), "mutate")
        tracker = CompletionTracker()
        path = r"C:\Users\daanv\Desktop\Jarvis-Test\notepad-e2e.txt"
        tracker.record(
            "desktop",
            {"action": "write", "path": path, "text": "JARVIS-DESKTOP-E2E"},
            True,
            f"Wrote {path} via Notepad UI Automation",
        )
        baseline = len(tracker.steps)
        tracker.record("desktop", {"action": "windows"}, True, "Notepad\nExplorer")
        self.assertEqual(tracker.steps[-1].kind, "inspect")
        mutated = any(
            step.kind == "mutate" and step.success and not step.blocked
            for step in tracker.steps[baseline:]
        )
        self.assertFalse(mutated)

    def test_browser_snapshots_do_not_complete_without_saved_file(self) -> None:
        tracker = CompletionTracker()
        tracker.record("browser", {"action": "open", "url": "https://example.com"}, True, "opened")
        tracker.record("browser", {"action": "snapshot"}, True, "Example Domain")
        tracker.record("browser", {"action": "snapshot"}, True, "Example Domain")
        self.assertFalse(tracker.should_complete())

    def test_report_never_empty_after_success(self) -> None:
        tracker = CompletionTracker()
        tracker.record("filesystem", {"action": "write", "path": r"C:\tmp\a.txt"}, True, "Wrote C:\\tmp\\a.txt (4 bytes)")
        tracker.record("filesystem", {"action": "read", "path": r"C:\tmp\a.txt"}, True, "ok")
        tracker.should_complete()
        report = tracker.synthesize_report("write a.txt")
        self.assertTrue(report.startswith("Completed"))
        self.assertGreater(len(report), 40)


if __name__ == "__main__":
    unittest.main()
