"""RFC-0106 Wave B: HexStrike stub / missing-dep honesty (never look 'running')."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.security import hexstrike_compat
from app.security.hexstrike import HEXSTRIKE, HexStrikeManager
from app.security.hexstrike_compat import (
    ALWAYS_STUBBED_OPTIONALS,
    DISABLED_MESSAGE,
    install_optional_stubs,
    package_is_stubbed,
    read_stub_manifest,
    write_stub_manifest,
)
from app.security.hexstrike_operator import (
    operate,
    refresh_discovered_catalog,
    _apply_catalog_honesty,
    _capabilities_from_health,
)


@pytest.fixture
def operator_store(jarvis_env, monkeypatch):
    from app.security import hexstrike_operator as hop

    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.security.hexstrike_operator.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    HEXSTRIKE._process = SimpleNamespace(pid=1, returncode=None)
    HEXSTRIKE._loopback_healthy = True
    hop._CATALOG_CACHE = []
    yield tmp
    HEXSTRIKE._process = None
    HEXSTRIKE._loopback_healthy = False
    HEXSTRIKE._health = {}
    hop._CATALOG_CACHE = []


def test_compat_writes_stub_manifest_and_marks_modules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stubbed = install_optional_stubs(force=True)
    assert "mitmproxy" in stubbed
    assert "selenium" in stubbed
    state = tmp_path / "jarvis-state"
    path = write_stub_manifest(stubbed, state)
    assert path.is_file()
    manifest = read_stub_manifest(state)
    assert manifest["status"] == "unavailable"
    assert manifest["invokable"] is False
    assert "mitmproxy" in manifest["stubbed"]
    assert "selenium" in manifest["stubbed"]
    import mitmproxy

    assert getattr(mitmproxy, hexstrike_compat.STUB_MARKER) is True


def test_package_is_stubbed_matches_optional_extras():
    assert package_is_stubbed("mitmproxy", ALWAYS_STUBBED_OPTIONALS)
    assert package_is_stubbed("selenium_browser", ALWAYS_STUBBED_OPTIONALS)
    assert package_is_stubbed("http:mitmproxy", ALWAYS_STUBBED_OPTIONALS)
    assert not package_is_stubbed("nmap", ALWAYS_STUBBED_OPTIONALS)


def test_health_status_strings_never_treat_stub_as_available():
    rows = _capabilities_from_health(
        {
            "nmap": "ok",
            "mitmproxy": "available",  # upstream may lie after import stub
            "selenium": "stub",
            "ghost": "missing",
        }
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id["http:nmap"]["available"] is True
    assert by_id["http:selenium"]["available"] is False
    assert by_id["http:ghost"]["available"] is False
    # Honesty pass forces stubbed packages unavailable even if upstream said "available".
    honest = _apply_catalog_honesty(rows, suite_running=True, stubbed=list(ALWAYS_STUBBED_OPTIONALS))
    honest_by_id = {row["id"]: row for row in honest}
    assert honest_by_id["http:mitmproxy"]["available"] is False
    assert honest_by_id["http:mitmproxy"]["stub"] is True
    assert honest_by_id["http:mitmproxy"]["status"] == "unavailable"
    assert DISABLED_MESSAGE in (honest_by_id["http:mitmproxy"].get("guidance") or "")


def test_catalog_honesty_marks_offline_http_unavailable():
    rows = [
        {
            "id": "http:scanner_one",
            "source": "http",
            "title": "scanner_one",
            "available": True,
            "missing_dependencies": [],
            "status": "running",
        }
    ]
    honest = _apply_catalog_honesty(rows, suite_running=False, stubbed=[])
    assert honest[0]["available"] is False
    assert honest[0]["status"] == "unavailable"
    assert "hexstrike-suite" in honest[0]["missing_dependencies"]


@pytest.mark.asyncio
async def test_status_process_without_health_is_not_running(monkeypatch, jarvis_env):
    manager = HexStrikeManager()
    monkeypatch.setattr(manager, "_settings_view", lambda: ("", "", "127.0.0.1", 18888))
    manager._process = SimpleNamespace(pid=4242, returncode=None)  # type: ignore[assignment]
    manager._loopback_healthy = True

    async def fail_probe(url: str) -> bool:
        assert "18888" in url
        return False

    monkeypatch.setattr(manager, "_probe_health", fail_probe)
    snapshot = await manager.status(enrich=True)
    assert snapshot.running is False
    assert snapshot.pid is None
    assert snapshot.tools == {}
    assert "unreachable" in snapshot.last_error.lower()
    assert snapshot.stub_status == "unavailable"
    assert "mitmproxy" in snapshot.optional_stubs
    payload = snapshot.as_dict()
    assert payload["running"] is False
    assert payload["optional_extras_available"] is False
    assert payload["stub_status"] == "unavailable"


@pytest.mark.asyncio
async def test_status_healthy_probe_can_report_running(monkeypatch):
    manager = HexStrikeManager()
    monkeypatch.setattr(manager, "_settings_view", lambda: ("", "", "127.0.0.1", 18888))
    manager._process = SimpleNamespace(pid=5252, returncode=None)  # type: ignore[assignment]
    manager._loopback_healthy = False
    manager._health = {"tools_status": {"nmap": "ok", "mitmproxy": "available"}}

    async def ok_probe(url: str) -> bool:
        manager._loopback_healthy = True
        return True

    async def fake_enrich(snapshot):
        snapshot.tools = manager._sanitize_tools_for_stubs(
            {"nmap": "ok", "mitmproxy": "available"},
            snapshot.optional_stubs,
        )

    monkeypatch.setattr(manager, "_probe_health", ok_probe)
    monkeypatch.setattr(manager, "_enrich", fake_enrich)
    snapshot = await manager.status(enrich=True)
    assert snapshot.running is True
    assert snapshot.pid == 5252
    assert snapshot.tools.get("nmap") == "ok"
    assert snapshot.tools.get("mitmproxy") == "unavailable"


@pytest.mark.asyncio
async def test_refresh_catalog_stubbed_tools_not_available(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"nmap": "ok", "mitmproxy": "available", "selenium": "ready"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=["mitmproxy", "selenium"],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr(
        "app.security.hexstrike_operator.shutil.which",
        lambda name: "/usr/bin/nmap" if name == "nmap" else None,
    )
    catalog = await refresh_discovered_catalog(force=True)
    by_id = {item["id"]: item for item in catalog}
    assert by_id["http:mitmproxy"]["available"] is False
    assert by_id["http:selenium"]["available"] is False
    assert by_id["http:nmap"]["available"] is True


@pytest.mark.asyncio
async def test_operate_refuses_stubbed_capability(operator_store, monkeypatch):
    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=True,
            install_path=str(operator_store),
            tools={"mitmproxy": "available"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=["mitmproxy", "selenium"],
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    await refresh_discovered_catalog(force=True)
    with pytest.raises(RuntimeError, match="optional stub|unavailable"):
        await operate("http:mitmproxy", {})


@pytest.mark.asyncio
async def test_operate_refuses_when_suite_not_running(operator_store, monkeypatch):
    HEXSTRIKE._process = None
    HEXSTRIKE._loopback_healthy = False

    async def fake_status(*, enrich=True):
        return SimpleNamespace(
            running=False,
            install_path=str(operator_store),
            tools={"scanner_one": "ok"},
            host="127.0.0.1",
            port=8888,
            python_executable="python",
            optional_stubs=list(ALWAYS_STUBBED_OPTIONALS),
        )

    monkeypatch.setattr(HEXSTRIKE, "status", fake_status)
    monkeypatch.setattr("app.licensing.entitlements.hexstrike_access_mode", lambda now=None: "full")
    # Seed cache as if a prior run marked the tool available.
    from app.security import hexstrike_operator as hop

    hop._CATALOG_CACHE = [
        {
            "id": "http:scanner_one",
            "source": "http",
            "title": "scanner_one",
            "upstream_path": "api/tools/scanner_one",
            "available": True,
            "missing_dependencies": [],
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        }
    ]
    with pytest.raises(RuntimeError, match="unavailable"):
        await operate("http:scanner_one", {})


@pytest.mark.asyncio
async def test_proxy_fail_closed_when_health_down(monkeypatch):
    manager = HexStrikeManager()
    monkeypatch.setattr(manager, "_settings_view", lambda: ("", "", "127.0.0.1", 18888))
    manager._process = SimpleNamespace(pid=1, returncode=None)  # type: ignore[assignment]
    manager._loopback_healthy = True

    async def fail_probe(url: str) -> bool:
        return False

    monkeypatch.setattr(manager, "_probe_health", fail_probe)
    with pytest.raises(RuntimeError, match="not running"):
        await manager.post_operator("api/tools/nmap", {"target": "127.0.0.1"})
