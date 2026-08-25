from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.artifacts import expected_output_paths, missing_outputs, outputs_ready, required_snippets
from app.agent.completion import CompletionTracker
from app.agent.verify import inspect_artifacts


class ArtifactExtractionTests(unittest.TestCase):
    def test_named_desktop_file(self) -> None:
        prompt = (
            "Create a folder on the desktop named Jarvis-Test and write a text file named "
            "system-specs.txt containing the current system specifications."
        )
        paths = expected_output_paths(prompt)
        self.assertTrue(any(p.lower().endswith("jarvis-test\\system-specs.txt") or p.lower().endswith("jarvis-test/system-specs.txt") for p in paths))
        desktop = str(Path.home() / "Desktop" / "Jarvis-Test" / "system-specs.txt")
        self.assertEqual(Path(paths[0]).resolve(), Path(desktop).resolve())

    def test_full_windows_path(self) -> None:
        target = Path.home() / "Desktop" / "Jarvis-Test" / "primes.txt"
        prompt = f"save the result to {target}. Verify the file contains 100 numbers."
        paths = expected_output_paths(prompt)
        self.assertEqual(Path(paths[0]).resolve(), target.resolve())

    def test_relative_output_in_project(self) -> None:
        project = Path(tempfile.mkdtemp(prefix="jarvis-broken-"))
        prompt = (
            f"Find out why the Python project at {project} fails, fix it, and verify the fix by running python main.py. "
            "The program should write 100 primes to output.txt."
        )
        paths = expected_output_paths(prompt)
        self.assertTrue(any(Path(p).name == "output.txt" for p in paths))
        self.assertEqual(Path(paths[0]).parent.resolve(), project.resolve())

    def test_image_path_is_not_an_output(self) -> None:
        image = Path(tempfile.mkdtemp()) / "vision-target.png"
        image.write_bytes(b"x")
        out = Path.home() / "Desktop" / "Jarvis-Test" / "vision-result.txt"
        prompt = f"Look at this image: {image}. Save your answer to {out}."
        paths = expected_output_paths(prompt)
        self.assertTrue(all(Path(p).suffix.lower() != ".png" for p in paths))
        self.assertTrue(any(Path(p).name == "vision-result.txt" for p in paths))

    def test_recovered_word(self) -> None:
        self.assertEqual(required_snippets("write a file containing the word RECOVERED and the date"), ["RECOVERED"])


class ExpectedFileGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t05-"))

    def test_should_not_complete_while_named_file_missing(self) -> None:
        path = self.tmp / "primes.txt"
        prompt = f"save the primes to {path}"
        tracker = CompletionTracker()
        tracker.record("filesystem", {"action": "write", "path": str(self.tmp / "notes.txt"), "content": "x"}, True, "Wrote notes")
        (self.tmp / "notes.txt").write_text("x", encoding="utf-8")
        for _ in range(8):
            tracker.record("filesystem", {"action": "list", "path": str(self.tmp)}, True, "notes.txt")
        self.assertFalse(tracker.should_complete(prompt))
        self.assertTrue(missing_outputs(prompt))

    def test_should_complete_when_requested_file_exists(self) -> None:
        path = self.tmp / "primes.txt"
        path.write_text("2\n3\n5\n97\n", encoding="utf-8")
        prompt = f"save the primes to {path}"
        tracker = CompletionTracker()
        tracker.record("python", {"action": "run_code", "code": "print('ok')"}, True, f"wrote {path}")
        self.assertTrue(outputs_ready(prompt))
        self.assertTrue(tracker.should_complete(prompt))

    def test_verify_inspects_prompt_path_without_filesystem_write(self) -> None:
        path = self.tmp / "recovery.txt"
        path.write_text("RECOVERED 2026-08-22", encoding="utf-8")
        prompt = f"write {path} containing the word RECOVERED"
        tracker = CompletionTracker()
        tracker.record("python", {"action": "run_code"}, True, f"wrote {path}")
        result = inspect_artifacts(tracker, prompt)
        self.assertTrue(result.ok)
        self.assertTrue(any("recovery.txt" in c.path.lower() and c.ok for c in result.checks))

    def test_terminal_run_in_project_counts_as_producing_output_txt(self) -> None:
        project = self.tmp / "broken_primes"
        project.mkdir()
        out = project / "output.txt"
        out.write_text("\n".join(str(n) for n in range(100)), encoding="utf-8")
        prompt = f"Fix the Python project at {project}. The program should write 100 primes to output.txt."
        tracker = CompletionTracker()
        tracker.record(
            "terminal",
            {
                "command": f"cd {project} && python main.py",
                "shell": "cmd",
            },
            True,
            "exit_code=0\nwrote 100 primes\n",
        )
        self.assertTrue(tracker.touched_expected(prompt))
        self.assertTrue(tracker.should_complete(prompt))
        result = inspect_artifacts(tracker, prompt)
        self.assertTrue(result.ok)

    def test_leftover_expected_file_does_not_complete_from_unrelated_write(self) -> None:
        path = self.tmp / "primes.txt"
        path.write_text("2\n97\n", encoding="utf-8")
        prompt = f"save the primes to {path}"
        tracker = CompletionTracker()
        notes = self.tmp / "notes.txt"
        notes.write_text("scratch", encoding="utf-8")
        tracker.record("filesystem", {"action": "write", "path": str(notes), "content": "scratch"}, True, "Wrote notes")
        tracker.record("filesystem", {"action": "read", "path": str(notes)}, True, "scratch")
        self.assertFalse(tracker.touched_expected(prompt))
        self.assertFalse(tracker.should_complete(prompt))
        result = inspect_artifacts(tracker, prompt)
        self.assertFalse(result.ok)
        self.assertIn("has not created", result.summary().lower())


if __name__ == "__main__":
    unittest.main()
