import os
import subprocess
import sys

from app.hardware import _office_installed
from app.tools.browser import BrowserTool
from app.tools.docker_tools import DockerTool
from app.tools.git_tools import GitTool
from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool, _default_shell
from app.tools.web_fetch import WebFetchTool


async def test_docker_run_logs_inspect_require_targets(monkeypatch):
    monkeypatch.setattr("app.tools.docker_tools.shutil.which", lambda _: "/usr/bin/docker")

    async def boom(*_args, **_kwargs):
        raise AssertionError("docker must not be spawned without a target")

    monkeypatch.setattr("asyncio.create_subprocess_exec", boom)
    run = await DockerTool().execute(action="run")
    logs = await DockerTool().execute(action="logs")
    inspect = await DockerTool().execute(action="inspect")
    assert not run.success and "image" in run.error.lower()
    assert not logs.success and "container" in logs.error.lower()
    assert not inspect.success and "container or image" in inspect.error.lower()


async def test_browser_close_does_not_launch(monkeypatch):
    from app.tools import browser as browser_mod

    launched = []

    async def boom(_headless):
        launched.append(True)
        raise AssertionError("close must not launch Chromium")

    browser_mod._page = None
    browser_mod._context = None
    browser_mod._playwright = None
    browser_mod._pages = ["stale"]
    monkeypatch.setattr(browser_mod, "_ensure_page", boom)
    result = await BrowserTool(lambda: {}).execute(action="close")
    assert result.success
    assert launched == []
    assert browser_mod._pages == []
    assert "not open" in result.output.lower()


def test_python_uses_current_interpreter():
    assert PythonTool()._python_bin(None) == sys.executable


def test_terminal_defaults_to_bash_on_linux():
    if os.name == "nt":
        assert _default_shell() == "powershell"
    else:
        assert _default_shell() == "bash"


async def test_terminal_run_without_shell_uses_platform_default(tmp_path):
    if os.name == "nt":
        return
    result = await TerminalTool().execute(command="echo jarvis-default-shell", working_directory=str(tmp_path))
    assert result.success, result.error
    assert "jarvis-default-shell" in result.output


def test_office_probe_does_not_dispatch_com(monkeypatch):
    monkeypatch.setattr("app.hardware.platform.system", lambda: "Windows")
    monkeypatch.setattr("app.hardware.Path.exists", lambda self: False)
    assert _office_installed() is False


async def test_git_checkpoint_creates_branch_and_keeps_edits(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "Jarvis", "GIT_AUTHOR_EMAIL": "jarvis@test", "GIT_COMMITTER_NAME": "Jarvis", "GIT_COMMITTER_EMAIL": "jarvis@test"}
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "jarvis@test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Jarvis"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, env=env)
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    result = await GitTool().execute(action="checkpoint", path=str(repo))
    assert result.success, result.error
    assert "jarvis-checkpoint-" in result.output
    assert (repo / "a.txt").read_text(encoding="utf-8") == "two\n"
    branches = await GitTool().execute(action="branch", path=str(repo))
    assert "jarvis-checkpoint-" in branches.output


async def test_web_fetch_post_sends_json_body(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        is_success = True
        text = '{"ok":true}'
        headers = {"content-type": "application/json"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["client_headers"] = kwargs.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return FakeResponse()

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", FakeClient)
    result = await WebFetchTool().execute(
        url="https://example.test/api",
        method="POST",
        json_body={"q": "jarvis"},
        headers={"X-Test": "1"},
    )
    assert result.success
    assert captured["method"] == "POST"
    assert captured["json"] == {"q": "jarvis"}
    assert captured["client_headers"]["X-Test"] == "1"
    assert captured["client_headers"]["User-Agent"] == "JarvisLocal/1.0"
