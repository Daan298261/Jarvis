"""Small project adapters; failures propagate to the standards runner."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".verify" / "tools"
TOOL_PYTHON = TOOLS / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True, timeout=900)


async def database() -> None:
    """Upgrade a legacy tasks table twice, preserving its existing row."""
    with tempfile.TemporaryDirectory(prefix="anzu-db-gate-") as scratch:
        os.environ["JARVIS_ROOT"] = scratch
        sys.path.insert(0, str(ROOT / "backend"))
        from app.db import session

        path = Path(scratch) / "legacy.db"
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute("CREATE TABLE tasks (id VARCHAR PRIMARY KEY)")
                connection.execute("INSERT INTO tasks (id) VALUES ('preserve-me')")
        try:
            await session.configure_database(path=path)
            await session.init_db()
            await session.init_db()
            with closing(sqlite3.connect(path)) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
                assert {"execution_mode", "schema_errors", "response_route"} <= columns
                assert connection.execute("SELECT id FROM tasks").fetchall() == [("preserve-me",)]
            print("Legacy schema upgrade is idempotent and preserved the existing row.")
        finally:
            await session.dispose_database_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=["install-tools", "install-browsers", "lint", "dependency-scan", "database", "coverage"])
    check = parser.parse_args().check
    if check == "install-tools":
        if not TOOL_PYTHON.is_file():
            venv.EnvBuilder(with_pip=True).create(TOOLS)
        run(str(TOOL_PYTHON), "-m", "pip", "install", "-r", "scripts/quality/requirements.txt")
    elif check == "install-browsers":
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(ROOT / ".verify" / "browsers"))
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], cwd=ROOT, env=env, check=True, timeout=900)
    elif check == "lint":
        run(str(TOOL_PYTHON), "-m", "ruff", "check", "--select", "E9,F63,F7,F82", "backend", "tests", "scripts")
    elif check == "dependency-scan":
        # Audit the actual application interpreter, not the isolated tooling venv.
        run(str(TOOL_PYTHON), "-m", "pip_audit", "--strict", "--progress-spinner", "off", "--path", str(Path(sys.executable).resolve().parent.parent / "Lib/site-packages"))
    elif check == "coverage":
        tool_packages = TOOLS / ("Lib/site-packages" if os.name == "nt" else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
        env = dict(os.environ, JARVIS_SKIP_MODEL="1", PYTHONPATH=str(tool_packages) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_manager_model_processes.py", "--cov=app.manager.model_processes", "--cov-branch", "--cov-fail-under=85", "--cov-report=term-missing", "--cov-report=xml:.verify/model-process-coverage.xml"], cwd=ROOT, env=env, check=True, timeout=300)
    else:
        asyncio.run(database())


if __name__ == "__main__":
    main()
