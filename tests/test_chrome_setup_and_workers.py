import base64
import io
import json
from pathlib import Path
import zipfile

from app.tools import chrome_setup
from app.workers import isolated_runtime


def test_stable_extension_id_and_package():
    identity = chrome_setup.extension_id()
    assert len(identity) == 32 and set(identity) <= set("abcdefghijklmnop")
    with zipfile.ZipFile(io.BytesIO(chrome_setup.connector_package())) as package:
        manifest = json.loads(package.read("chrome/manifest.json"))
        assert manifest["key"]
        assert "webNavigation" in manifest["permissions"] and "downloads" in manifest["permissions"]
        filters = json.loads(package.read("chrome/filters/easylist-domains.json"))
        assert filters["license"] == "CC-BY-SA-3.0"
        assert len(filters["domains"]["any"]) > 40000


def test_worker_ready_requires_a_verified_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(isolated_runtime, "runtime_root", lambda worker_id: tmp_path / worker_id)
    assert isolated_runtime.installed_worker_python("cua") is None
    python = isolated_runtime.runtime_python("cua")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"placeholder")
    assert isolated_runtime.installed_worker_python("cua") is None
    (tmp_path / "cua" / "ready.json").write_text(json.dumps({"verified":True}))
    assert isolated_runtime.installed_worker_python("cua") == python


async def test_cua_sdk_route_uses_local_model_and_no_guessed_cli(monkeypatch):
    from app.workers.computer import CuaBackend
    from app.tools.base import ToolResult
    calls = []
    monkeypatch.setattr(isolated_runtime, "installed_worker_python", lambda worker_id: Path("isolated-python"))
    async def run(worker_id, payload, **kwargs):
        calls.append((worker_id, payload))
        return ToolResult(True, "verified")
    monkeypatch.setattr(isolated_runtime, "run_isolated", run)
    result = await CuaBackend().run("Inspect the calculator", app="Calculator")
    assert result.success and calls[0][0] == "cua"
    assert calls[0][1]["base_url"].startswith("http://127.0.0.1:")
    assert "api_key" in calls[0][1]
