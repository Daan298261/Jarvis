from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.completion import CompletionTracker
from app.agent.verify import inspect_artifacts


class IndependentVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t02-"))

    def test_matching_write_content_passes(self) -> None:
        path = self.tmp / "smoke.txt"
        path.write_text("READY", encoding="utf-8")
        tracker = CompletionTracker()
        tracker.record("filesystem", {"action": "write", "path": str(path), "content": "READY"}, True, "Wrote file")
        result = inspect_artifacts(tracker, f"write READY to {path}")
        self.assertTrue(result.ok)
        self.assertTrue(any(c.ok for c in result.checks))
        self.assertIn("matches", result.summary().lower())

    def test_missing_file_fails(self) -> None:
        path = self.tmp / "missing.txt"
        tracker = CompletionTracker()
        tracker.record("filesystem", {"action": "write", "path": str(path), "content": "READY"}, True, "Wrote file")
        result = inspect_artifacts(tracker)
        self.assertFalse(result.ok)
        self.assertIn("does not exist", result.summary())
        self.assertIn("Independent verification failed", result.repair_prompt())

    def test_content_mismatch_fails(self) -> None:
        path = self.tmp / "wrong.txt"
        path.write_text("NOPE", encoding="utf-8")
        tracker = CompletionTracker()
        tracker.record("filesystem", {"action": "write", "path": str(path), "content": "READY"}, True, "Wrote file")
        result = inspect_artifacts(tracker)
        self.assertFalse(result.ok)
        self.assertIn("mismatch", result.summary().lower())

    def test_no_file_artifacts_does_not_block(self) -> None:
        tracker = CompletionTracker()
        tracker.record("browser", {"action": "open", "url": "https://example.com"}, True, "opened")
        result = inspect_artifacts(tracker)
        self.assertTrue(result.ok)

    def test_python_output_path_mentioned_in_prompt_is_inspected(self) -> None:
        path = self.tmp / "primes.txt"
        path.write_text("2\n3\n5\n", encoding="utf-8")
        tracker = CompletionTracker()
        tracker.record(
            "python",
            {"action": "run_code", "code": "print('ok')"},
            True,
            f"wrote {path}",
        )
        result = inspect_artifacts(tracker, f"save primes to {path}")
        self.assertTrue(result.ok)
        self.assertTrue(any(c.path.lower() == str(path).lower() and c.ok for c in result.checks))


if __name__ == "__main__":
    unittest.main()
