from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backup import KEEP, get_backup, list_backups, restore_database_files, restore_settings, snapshot
from app.tools.filesystem import FilesystemTool
from app.tools.git_tools import GitTool


class BackupStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-t21-"))
        self.settings = self.tmp / "settings.json"
        self.db = self.tmp / "jarvis.db"
        self.bdir = self.tmp / "backups"
        self.settings.write_text(json.dumps({"autonomy": "trusted"}), encoding="utf-8")
        conn = sqlite3.connect(self.db)
        conn.execute("create table items(id integer primary key, name text)")
        conn.execute("insert into items(name) values ('alpha')")
        conn.commit()
        conn.close()
        self.patches = [
            patch("app.backup.config.settings_path", lambda: self.settings),
            patch("app.backup.db_path", lambda: self.db),
            patch("app.backup.backups_dir", self._backups_dir),
        ]
        for item in self.patches:
            item.start()

    def _backups_dir(self) -> Path:
        self.bdir.mkdir(parents=True, exist_ok=True)
        return self.bdir

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()

    def test_snapshot_copies_settings_and_db(self) -> None:
        row = snapshot("startup")
        assert row is not None
        folder = Path(row["path"]) if "path" in row else self.bdir / row["id"]
        if "path" not in row:
            folder = self.bdir / row["id"]
        self.assertTrue((self.bdir / row["id"] / "settings.json").exists())
        self.assertTrue((self.bdir / row["id"] / "jarvis.db").exists())
        listed = list_backups()
        self.assertEqual(listed[0]["id"], row["id"])
        self.assertIn("settings.json", listed[0]["files"])
        self.assertIn("jarvis.db", listed[0]["files"])

    def test_restore_settings_puts_previous_file_back(self) -> None:
        first = snapshot("manual")
        assert first is not None
        self.settings.write_text(json.dumps({"autonomy": "autonomous"}), encoding="utf-8")
        restore_settings(first["id"])
        payload = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(payload["autonomy"], "trusted")

    def test_restore_database_puts_rows_back(self) -> None:
        first = snapshot("manual")
        assert first is not None
        conn = sqlite3.connect(self.db)
        conn.execute("insert into items(name) values ('beta')")
        conn.commit()
        conn.close()
        restore_database_files(first["id"])
        conn = sqlite3.connect(self.db)
        names = [row[0] for row in conn.execute("select name from items order by id").fetchall()]
        conn.close()
        self.assertEqual(names, ["alpha"])

    def test_unchanged_automatic_snapshot_is_skipped(self) -> None:
        first = snapshot("startup")
        assert first is not None
        second = snapshot("startup")
        assert second is not None
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(list_backups()), 1)

    def test_db_change_creates_new_automatic_snapshot(self) -> None:
        first = snapshot("startup")
        assert first is not None
        conn = sqlite3.connect(self.db)
        conn.execute("insert into items(name) values ('gamma')")
        conn.commit()
        conn.close()
        second = snapshot("startup")
        assert second is not None
        self.assertNotEqual(first["id"], second["id"])

    def test_manual_snapshot_always_writes(self) -> None:
        snapshot("manual")
        snapshot("manual")
        self.assertGreaterEqual(len(list_backups()), 2)

    def test_prune_keeps_a_cap(self) -> None:
        import app.backup as backup_mod

        previous = backup_mod.KEEP
        backup_mod.KEEP = 3
        try:
            for _ in range(5):
                conn = sqlite3.connect(self.db)
                conn.execute("insert into items(name) values ('x')")
                conn.commit()
                conn.close()
                snapshot("startup")
            self.assertLessEqual(len(list_backups()), 3)
        finally:
            backup_mod.KEEP = previous

    def test_get_backup_rejects_path_escape(self) -> None:
        self.assertIsNone(get_backup("../secrets"))
        self.assertIsNone(get_backup("a/b"))


class FilesystemRestoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_keeps_sidecar_and_restore_reverts(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t21-fs-"))
        target = tmp / "notes.txt"
        target.write_text("one", encoding="utf-8")
        tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp)], "backup_enabled": True})
        wrote = await tool.execute(action="write", path=str(target), content="two")
        self.assertTrue(wrote.success)
        self.assertEqual(target.read_text(encoding="utf-8"), "two")
        sidecars = list(tmp.glob("notes.txt.bak-*"))
        self.assertEqual(len(sidecars), 1)
        restored = await tool.execute(action="restore", path=str(target))
        self.assertTrue(restored.success)
        self.assertEqual(target.read_text(encoding="utf-8"), "one")

    async def test_backup_sidecars_are_capped(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-t21-fs-cap-"))
        target = tmp / "notes.txt"
        target.write_text("0", encoding="utf-8")
        tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp)], "backup_enabled": True})
        for i in range(6):
            await tool.execute(action="write", path=str(target), content=str(i + 1))
        self.assertLessEqual(len(list(tmp.glob("notes.txt.bak-*"))), 3)


class GitCheckpointTests(unittest.IsolatedAsyncioTestCase):
    def _repo(self) -> Path:
        repo = Path(tempfile.mkdtemp(prefix="jarvis-t21-git-"))
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "jarvis@local"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Jarvis"], cwd=repo, check=True, capture_output=True)
        (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        return repo

    async def test_checkpoint_then_restore_reverts_file(self) -> None:
        repo = self._repo()
        tool = GitTool()
        status = await tool.execute(action="status", path=str(repo))
        self.assertTrue(status.success)
        created = await tool.execute(action="checkpoint", path=str(repo))
        self.assertTrue(created.success, created.error or created.output)
        self.assertIn("jarvis-checkpoint-", created.output)
        (repo / "app.py").write_text("print('broken')\n", encoding="utf-8")
        listed = await tool.execute(action="checkpoints", path=str(repo))
        self.assertIn("jarvis-checkpoint-", listed.output)
        restored = await tool.execute(action="restore", path=str(repo), target="app.py")
        self.assertTrue(restored.success, restored.error or restored.output)
        self.assertEqual((repo / "app.py").read_text(encoding="utf-8"), "print('ok')\n")

    async def test_restore_rejects_non_checkpoint_ref(self) -> None:
        repo = self._repo()
        tool = GitTool()
        denied = await tool.execute(action="restore", path=str(repo), ref="main")
        self.assertFalse(denied.success)
        self.assertIn("jarvis-checkpoint", denied.error)

    async def test_checkpoint_includes_uncommitted_work(self) -> None:
        repo = self._repo()
        (repo / "app.py").write_text("print('wip')\n", encoding="utf-8")
        tool = GitTool()
        created = await tool.execute(action="checkpoint", path=str(repo))
        self.assertTrue(created.success, created.error or created.output)
        (repo / "app.py").write_text("print('later')\n", encoding="utf-8")
        restored = await tool.execute(action="restore", path=str(repo), target="app.py")
        self.assertTrue(restored.success, restored.error or restored.output)
        self.assertEqual((repo / "app.py").read_text(encoding="utf-8"), "print('wip')\n")


class BackupApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_rejects_unknown_target(self) -> None:
        from fastapi import HTTPException

        from app.api.backups import RestoreBody, backups_restore

        with patch("app.api.backups.get_backup", return_value={"id": "x"}):
            with self.assertRaises(HTTPException) as raised:
                await backups_restore("x", RestoreBody(target="secrets"))
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
