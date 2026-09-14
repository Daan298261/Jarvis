from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.tools.capabilities import optional_workers
from app.workers import install as install_mod


def setup_function() -> None:
    for task in list(install_mod._TASKS.values()):
        task.cancel()
    install_mod.reset_install_jobs()


def teardown_function() -> None:
    install_mod.reset_install_jobs()


def test_optional_worker_allowlist_is_fixed():
    assert tuple(install_mod.SPECS) == install_mod.OPTIONAL_WORKER_IDS
    assert set(install_mod.SPECS) == {
        "browser-use",
        "ufo",
        "cua",
        "open-interpreter",
        "openhands",
    }
    ufo = install_mod.SPECS["ufo"][0]
    assert ufo.git_url == install_mod.UFO_GIT_URL
    assert "microsoft/UFO" in ufo.git_url
    assert all(attempt.pip_packages or attempt.git_url for spec in install_mod.SPECS.values() for attempt in spec)


def test_pip_cmd_never_takes_owner_supplied_packages():
    cmd = install_mod._pip_cmd("browser-use")
    assert cmd[:4] == [install_mod.sys.executable, "-m", "pip", "install"]
    assert cmd[-1] == "browser-use"
    assert "--break-system-packages" not in cmd


def test_catalog_marks_missing_workers_installable():
    workers = {item["id"]: item for item in optional_workers()}
    for worker_id in install_mod.OPTIONAL_WORKER_IDS:
        item = workers[worker_id]
        assert "installable" in item
        if not item["available"]:
            assert item["installable"] is True
            assert item["status"] in {"missing", "installing"}
        else:
            assert item["installable"] is False


def test_install_endpoint_starts_allowlisted_job(monkeypatch):
    async def fake_start(worker_id: str):
        assert worker_id == "openhands"
        return {
            "worker_id": worker_id,
            "status": "installing",
            "error": "",
            "detail": "Starting install…",
            "already_installed": False,
            "already_started": False,
        }

    monkeypatch.setattr("app.api.tools.start_worker_install", fake_start)
    monkeypatch.setattr("app.api.tools.optional_workers", lambda: [{"id": "openhands", "installable": True, "status": "installing"}])
    client = TestClient(app)
    response = client.post("/api/tools/optional-workers/openhands/install")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "installing"
    assert body["worker_id"] == "openhands"
    assert body["optional_workers"][0]["status"] == "installing"


def test_unknown_worker_install_is_rejected():
    client = TestClient(app)
    response = client.post("/api/tools/optional-workers/not-a-real-worker/install")
    assert response.status_code == 404
    assert "Unknown optional worker" in response.json()["detail"]


def test_path_traversal_worker_id_is_rejected():
    client = TestClient(app)
    response = client.post("/api/tools/optional-workers/../browser-use/install")
    assert response.status_code in {404, 405, 422}


async def test_already_installed_worker_does_not_run_pip(monkeypatch):
    class Ready:
        def available(self) -> bool:
            return True

        def probe(self) -> dict:
            return {"id": "browser-use", "name": "Browser Use", "available": True, "status": "ready"}

    ran = {"count": 0}

    def boom(_worker_id: str) -> None:
        ran["count"] += 1
        raise AssertionError("pip should not run when the worker is already present")

    monkeypatch.setattr(install_mod, "_backend", lambda _wid: Ready())
    monkeypatch.setattr(install_mod, "_install_worker", boom)
    body = await install_mod.start_worker_install("browser-use")
    assert body["already_installed"] is True
    assert body["status"] == "ready"
    assert ran["count"] == 0


def test_install_worker_uses_allowlisted_pip(monkeypatch):
    commands: list[list[str]] = []

    class Probe:
        ready = False

        def available(self) -> bool:
            return Probe.ready

        def probe(self) -> dict:
            return {
                "id": "browser-use",
                "name": "Browser Use",
                "kind": "optional",
                "available": Probe.ready,
                "status": "ready" if Probe.ready else "missing",
                "detail": "",
            }

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        if command[:4] == [install_mod.sys.executable, "-m", "pip", "install"]:
            Probe.ready = True
        return 0, "Successfully installed browser-use"

    monkeypatch.setattr(install_mod, "_backend", lambda _wid: Probe())
    monkeypatch.setattr(install_mod, "_run", fake_run)
    monkeypatch.setattr(install_mod, "_playwright_chromium", lambda: None)
    install_mod._install_worker("browser-use")
    assert commands
    pip = commands[0]
    assert pip[:4] == [install_mod.sys.executable, "-m", "pip", "install"]
    assert pip[-1] in {"browser-use[core]", "browser-use"}
    assert all("curl" not in part for cmd in commands for part in cmd)
    jobs = install_mod.snapshot_jobs()
    assert jobs["browser-use"]["status"] == "ready"


def test_ufo_install_clones_microsoft_repo_only(monkeypatch, tmp_path):
    commands: list[list[str]] = []

    class Probe:
        ready = False

        def available(self) -> bool:
            return Probe.ready

        def probe(self) -> dict:
            return {"id": "ufo", "available": Probe.ready, "status": "ready" if Probe.ready else "missing"}

    dest = tmp_path / "microsoft-ufo"
    dest.mkdir()
    (dest / "requirements.txt").write_text("pywinauto\n", encoding="utf-8")
    (dest / ".git").mkdir()

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        if command[:3] == [install_mod.sys.executable, "-m", "pip"]:
            Probe.ready = True
        return 0, "ok"

    monkeypatch.setattr(install_mod, "_backend", lambda _wid: Probe())
    monkeypatch.setattr(install_mod, "_run", fake_run)
    monkeypatch.setattr(install_mod, "_optional_worker_root", lambda: tmp_path)
    monkeypatch.setattr(install_mod.shutil, "which", lambda _name: "git")
    monkeypatch.setattr(install_mod, "_write_pth", lambda _name, _target: tmp_path / "jarvis.pth")
    monkeypatch.setattr(
        install_mod,
        "_clone_repo",
        lambda url, _target: None if url == install_mod.UFO_GIT_URL else (_ for _ in ()).throw(AssertionError(url)),
    )
    install_mod._install_worker("ufo")
    pip_cmds = [cmd for cmd in commands if cmd[:3] == [install_mod.sys.executable, "-m", "pip"]]
    assert pip_cmds
    assert "-r" in pip_cmds[0]


def test_clone_repo_rejects_unlisted_url(tmp_path):
    try:
        install_mod._clone_repo("https://evil.example/repo.git", tmp_path / "x")
    except RuntimeError as exc:
        assert "unlisted" in str(exc).lower()
    else:
        raise AssertionError("unlisted git URL must be refused")


async def test_start_install_returns_existing_in_flight_job(monkeypatch):
    class DummyTask:
        def done(self) -> bool:
            return False

    class Missing:
        def available(self) -> bool:
            return False

    monkeypatch.setattr(install_mod, "_backend", lambda _wid: Missing())
    install_mod._set_job("cua", status="installing", error="", detail="in flight")
    install_mod._TASKS["cua"] = DummyTask()  # type: ignore[assignment]
    result = await install_mod.start_worker_install("cua")
    assert result["already_started"] is True
    assert result["status"] == "installing"
