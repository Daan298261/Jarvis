from __future__ import annotations

import asyncio
import os
import sys

from fastapi.testclient import TestClient

from app.coding.catalog import probe_cursor_models
from app.coding.routing import estimate_complexity, recommend_from_history
from app.coding.usage import estimate_cost_usd, record_usage, usage_summary
from app.config import AppSettings
from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool
from app.tools.git_tools import GitTool
from app.tools.office import OfficeTool
from app.tools.python_exec import PythonTool
from app.tools.terminal import default_shell
from app.tools.web_fetch import WebFetchTool


def test_composer_cost_uses_published_rates():
    # 1M in + 1M cached + 1M out = 0.50 + 0.20 + 2.50
    assert estimate_cost_usd("composer-2.5", 1_000_000, 1_000_000, 1_000_000) == 3.2
    assert estimate_cost_usd("local-qwen", 50_000, 0, 8_000) == 0.0
    grok = estimate_cost_usd("grok-4.6", 500_000, 0, 200_000)
    assert grok == 2.2


def test_fast_models_are_not_selectable_by_default():
    probe = probe_cursor_models(AppSettings())
    assert probe["status"] == "not_connected"
    assert probe["allow_fast_variants"] is False
    by_id = {item["id"]: item for item in probe["models"]}
    assert by_id["composer-2.5"]["selectable"] is True
    assert by_id["composer-2.5-fast"]["selectable"] is False
    assert "Fast" in by_id["composer-2.5-fast"]["blocked_reason"]


def test_allowing_fast_unlocks_fast_variants():
    settings = AppSettings()
    settings.coding.allow_fast_variants = True
    probe = probe_cursor_models(settings)
    by_id = {item["id"]: item for item in probe["models"]}
    assert by_id["composer-2.5-fast"]["selectable"] is True


def test_complexity_keeps_docs_local_and_architecture_paid():
    assert estimate_complexity("rename the changelog file", "software engineering") < 40
    assert estimate_complexity("redesign the distributed architecture across the repo", "software engineering") >= 80


def test_history_keeps_successful_local_work_local():
    history = {
        "samples": 5,
        "local_samples": 5,
        "local_success_rate": 0.9,
        "composer_samples": 0,
        "composer_success_rate": None,
        "recent_local_failures": False,
    }
    rec = recommend_from_history(
        "add a pytest for the recovery helper",
        "software engineering",
        history,
        AppSettings(),
    )
    assert rec.worker == "local"
    assert rec.model == "local-qwen"
    assert rec.paid is False


def test_three_local_failures_escalate_to_composer():
    history = {
        "samples": 3,
        "local_samples": 3,
        "local_success_rate": 0.0,
        "composer_samples": 0,
        "composer_success_rate": None,
        "recent_local_failures": True,
    }
    rec = recommend_from_history(
        "fix the failing unit tests in this repository",
        "software engineering",
        history,
        AppSettings(),
    )
    assert rec.worker == "cursor_acp"
    assert rec.model == "composer-2.5"
    assert rec.fallback == "grok-4.6"


async def test_usage_summary_tracks_cost_per_verified_success(jarvis_env):
    await record_usage(
        worker="cursor_acp",
        model="composer-2.5",
        task_class="software engineering",
        input_tokens=1_000_000,
        cached_tokens=0,
        output_tokens=0,
        verified_success=True,
        first_attempt_success=True,
    )
    await record_usage(
        worker="local",
        model="local-qwen",
        task_class="software engineering",
        verified_success=True,
        first_attempt_success=True,
    )
    summary = await usage_summary()
    assert summary["verified_successes"] == 2
    assert summary["cost_per_verified_success_usd"] == 0.25
    workers = {row["worker"]: row for row in summary["by_worker"]}
    assert workers["local"]["cost_usd"] == 0.0
    assert workers["cursor_acp"]["cost_per_verified_success"] == 0.5


async def test_coding_api_models_and_route(jarvis_env):
    from app.main import app

    client = TestClient(app)
    models = client.get("/api/coding/models")
    assert models.status_code == 200
    payload = models.json()
    assert payload["status"] == "not_connected"
    assert payload["composer_model"] == "composer-2.5"
    routed = client.post(
        "/api/coding/route",
        json={"prompt": "add a pytest for the recovery helper", "task_class": "software engineering"},
    )
    assert routed.status_code == 200
    assert routed.json()["worker"] in {"local", "deterministic", "cursor_acp"}
    overview = client.get("/api/coding")
    assert overview.status_code == 200
    assert "workers" in overview.json()


async def test_git_checkpoint_keeps_working_tree(tmp_path):
    async def git(*args: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        assert proc.returncode == 0

    await git("init")
    await git("config", "user.email", "jarvis@example.com")
    await git("config", "user.name", "Jarvis")
    await git("config", "commit.gpgsign", "false")
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    await git("add", "tracked.txt")
    await git("commit", "-m", "init")
    (tmp_path / "tracked.txt").write_text("two", encoding="utf-8")
    (tmp_path / "new.txt").write_text("untracked", encoding="utf-8")

    tool = GitTool()
    result = await tool.execute(action="checkpoint", path=str(tmp_path))
    assert result.success, result.error
    assert "Working tree was not reset" in result.output
    assert (tmp_path / "tracked.txt").read_text(encoding="utf-8") == "two"
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "untracked"
    assert result.data["branch"].startswith("jarvis-checkpoint-")


async def test_docker_requires_targets_before_cli():
    docker = DockerTool()
    run = await docker.execute(action="run")
    assert run.success is False
    assert "image is required" in run.error
    logs = await docker.execute(action="logs")
    assert "container is required" in logs.error
    inspect = await docker.execute(action="inspect")
    assert "container or image is required" in inspect.error


async def test_web_fetch_rejects_non_http():
    tool = WebFetchTool()
    for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/plain,hi"):
        result = await tool.execute(url=url)
        assert result.success is False
        assert "http/https" in result.error


async def test_office_info_does_not_dispatch():
    tool = OfficeTool()
    info = await tool.execute(app="word", action="info")
    assert info.success
    assert info.data["windows"] is False
    create = await tool.execute(app="word", action="create", destination="/tmp/no.docx")
    assert create.success is False
    assert "unavailable" in create.error.lower()


def test_python_uses_current_interpreter():
    tool = PythonTool()
    assert tool._python_bin(None) == sys.executable


def test_terminal_defaults_to_bash_on_linux():
    assert default_shell() in {"bash", "powershell"}
    if os.name != "nt":
        assert default_shell() == "bash"


async def test_browser_close_without_session_does_not_launch():
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    closed = await tool.execute(action="close")
    assert closed.success
    assert "not running" in closed.output.lower()
    missing = await tool.execute(action="open")
    assert missing.success is False
    assert "url is required" in missing.error
