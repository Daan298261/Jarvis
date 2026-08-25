from pathlib import Path

from app.agent.recovery import NOT_FOUND, UNAVAILABLE, alternatives_for
from app.tools.capabilities import capability_snapshot, optional_workers
from app.tools.docker_tools import DockerTool
from app.tools.registry import REGISTRY
from app.workers.browser import BrowserUseBackend, playwright_is_default
from app.workers.code import OpenHandsBackend
from app.workers.interpreter import OpenInterpreterBackend
from app.workers.local_llm import local_openai_env
from app.config import AppSettings


def test_playwright_remains_default_browser_backend():
    assert playwright_is_default() is True


def test_browser_use_and_openhands_are_integrated_adapters():
    workers = {item["id"]: item for item in optional_workers()}
    assert workers["browser-use"]["status"] in {"missing", "ready"}
    assert workers["openhands"]["status"] in {"missing", "ready"}
    assert workers["ufo"]["status"] in {"missing", "ready"}
    assert workers["cua"]["status"] in {"missing", "ready"}
    assert workers["open-interpreter"]["status"] in {"missing", "ready"}
    snap = capability_snapshot()
    native = {item["id"]: item for item in snap["native"]}
    assert "voice" in native
    assert native["playwright"]["detail"].lower().startswith("deterministic")


def test_local_worker_llm_stays_on_jarvis_endpoint():
    env = local_openai_env(AppSettings())
    assert env["OPENAI_BASE_URL"].startswith("http://127.0.0.1:8088")
    assert "openai.com" not in env["OPENAI_BASE_URL"]
    assert env["LLM_API_KEY"] == "local"


def test_browser_use_failure_falls_back_to_playwright():
    tools = [item.tool for item in alternatives_for("browser_use", UNAVAILABLE)]
    assert tools[0] == "browser"
    assert "web_fetch" in tools


def test_code_worker_failure_falls_back_to_native_coding_tools():
    tools = [item.tool for item in alternatives_for("code_worker", NOT_FOUND)]
    assert tools[:3] == ["python", "filesystem", "git"]


async def test_browser_use_tool_unavailable_without_package(jarvis_env):
    result = await REGISTRY.execute("browser_use", {"goal": "open example.com"})
    assert result.success is False
    assert "not installed" in result.error.lower()


async def test_browser_use_backend_runs_when_present(monkeypatch):
    backend = BrowserUseBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    async def fake_invoke(task, settings):
        assert "login" in task
        assert "example.com" in task
        return "found the login form"

    monkeypatch.setattr(backend, "_invoke", fake_invoke)
    result = await backend.run("find the login form", "https://example.com")
    assert result.success is True
    assert result.data["backend"] == "browser-use"
    assert "found the login form" in result.output


async def test_code_worker_status_and_sandbox(jarvis_env):
    status = await REGISTRY.execute("code_worker", {"action": "status"})
    assert status.success is True
    missing = await REGISTRY.execute(
        "code_worker",
        {"action": "delegate", "goal": "fix the tests", "path": str(jarvis_env["tmp"])},
    )
    assert missing.success is False
    assert "not installed" in missing.error.lower()
    denied = await REGISTRY.execute(
        "code_worker",
        {"action": "delegate", "goal": "fix the tests", "path": "/etc"},
    )
    assert denied.success is False
    assert "outside allowed" in denied.error.lower()


async def test_openhands_backend_reminds_jarvis_to_verify(monkeypatch, tmp_path):
    backend = OpenHandsBackend()
    monkeypatch.setattr(backend, "detect_kind", lambda: "cli")

    async def fake_invoke(command, workdir, settings, timeout):
        assert command[0] == "openhands"
        assert "--task" in command
        return ("changed files", "", 0)

    monkeypatch.setattr(backend, "_invoke", fake_invoke)
    result = await backend.run("fix the failing tests", tmp_path)
    assert result.success is True
    assert "independently inspect" in result.output.lower()
    assert result.data["kind"] == "cli"


async def test_open_interpreter_status_and_sandbox(jarvis_env):
    status = await REGISTRY.execute("open_interpreter", {"action": "status"})
    assert status.success is True
    assert "open interpreter" in status.output.lower()
    missing = await REGISTRY.execute(
        "open_interpreter",
        {"action": "delegate", "goal": "fix the tests", "path": str(jarvis_env["tmp"])},
    )
    assert missing.success is False
    assert "not installed" in missing.error.lower()
    denied = await REGISTRY.execute(
        "open_interpreter",
        {"action": "delegate", "goal": "fix the tests", "path": "/etc"},
    )
    assert denied.success is False
    assert "outside allowed" in denied.error.lower()


async def test_open_interpreter_backend_reminds_jarvis_to_verify(monkeypatch, tmp_path):
    backend = OpenInterpreterBackend()
    monkeypatch.setattr(backend, "detect_kind", lambda: "cli")

    async def fake_invoke(command, workdir, settings, timeout):
        assert command[0] == "interpreter"
        return ("changed files", "", 0)

    monkeypatch.setattr(backend, "_invoke", fake_invoke)
    result = await backend.run("install the project deps", tmp_path)
    assert result.success is True
    assert "independently inspect" in result.output.lower()
    assert result.data["backend"] == "open-interpreter"


async def test_ufo_and_cua_tools_degrade_when_missing(jarvis_env):
    ufo = await REGISTRY.execute("ufo", {"action": "run", "goal": "open notepad"})
    assert ufo.success is False
    assert "not installed" in ufo.error.lower()
    cua = await REGISTRY.execute("cua", {"action": "run", "goal": "open calculator"})
    assert cua.success is False
    assert "not installed" in cua.error.lower()


def test_open_interpreter_detects_alternate_module_and_cli(monkeypatch):
    backend = OpenInterpreterBackend()
    monkeypatch.setattr("app.workers.interpreter._module_available", lambda name: name == "open_interpreter")
    monkeypatch.setattr("app.workers.interpreter.shutil.which", lambda _name: None)
    assert backend.detect_kind() == "python-module"
    command = backend.build_command("fix tests", Path("."))
    assert command[1:3] == ["-m", "open_interpreter"]
    assert command[3:6] == ["--os", "-y", "-c"]

    monkeypatch.setattr("app.workers.interpreter._module_available", lambda _name: False)
    monkeypatch.setattr(
        "app.workers.interpreter.shutil.which",
        lambda name: "/usr/bin/open-interpreter" if name == "open-interpreter" else None,
    )
    assert backend.detect_kind() == "cli"
    command = backend.build_command("fix tests", Path("."))
    assert command[0] == "open-interpreter"
    assert command[1:4] == ["--os", "-y", "-c"]


async def test_docker_run_requires_image(monkeypatch):
    monkeypatch.setattr("app.tools.docker_tools.shutil.which", lambda _name: "/usr/bin/docker")
    result = await DockerTool().execute(action="run")
    assert result.success is False
    assert "image is required" in result.error


async def test_voice_command_and_listen(jarvis_env, monkeypatch):
    from io import BytesIO

    from fastapi import UploadFile

    from app.api.voice import VoiceIn, get_voice_status, voice_command, voice_listen

    created: list[tuple[str, str | None]] = []

    class FakeTask:
        def __init__(self, task_id: str, prompt: str) -> None:
            self.id = task_id
            self.status = "queued"
            self.prompt = prompt

    async def fake_create(prompt, autonomy=None, **kwargs):
        task = FakeTask(f"task-{len(created)+1}", prompt)
        created.append((prompt, autonomy))
        return task

    monkeypatch.setattr("app.api.voice.AGENT.create_task", fake_create)

    async def fake_transcribe(data: bytes, filename: str = "audio.webm") -> str:
        assert data == b"fake-audio"
        return "organize the inbox"

    monkeypatch.setattr("app.api.voice.transcribe_audio", fake_transcribe)

    command = await voice_command(VoiceIn(text="summarize notes"))
    assert command["transcript"] == "summarize notes"
    assert command["task_id"] == "task-1"
    assert created[0] == ("summarize notes", None)

    upload = UploadFile(filename="c.webm", file=BytesIO(b"fake-audio"))
    listened = await voice_listen(audio=upload, autonomy=None)
    assert listened["transcript"] == "organize the inbox"
    assert listened["task_id"] == "task-2"
    assert created[1] == ("organize the inbox", None)

    status = await get_voice_status()
    assert "stt_ready" in status
