from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class HistoryPageTests(unittest.TestCase):
    def test_history_page_shows_required_columns_and_continue(self) -> None:
        source = (ROOT / "frontend" / "src" / "pages" / "History.tsx").read_text(encoding="utf-8")
        self.assertIn("Last activity", source)
        self.assertIn("Worker / backend", source)
        self.assertIn("selected_worker", source)
        self.assertIn("updated_at", source)
        self.assertIn("result", source)
        self.assertIn("/continue", source)
        self.assertIn("Continue", source)
        self.assertIn("/tasks/${task.id}", source)
        self.assertNotIn("chain-of-thought", source.lower())

    def test_task_list_orders_by_last_activity(self) -> None:
        source = (ROOT / "backend" / "app" / "api" / "tasks.py").read_text(encoding="utf-8")
        self.assertIn("updated_at.desc()", source)


if __name__ == "__main__":
    unittest.main()
