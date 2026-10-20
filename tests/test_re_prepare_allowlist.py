"""store.prepare checks the allowed folders before any existence/link probe (follow-up to #660).

Same leak as prepare_ffs had: every target outside the allow-list must fail with the same
PermissionError (type and message), whether it exists, is missing, or is a link; the HTTP route
returns the identical 422 body. Inside the allow-list the link refusal and FileNotFoundError stay.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.main import app
from app.reverse_engineering import apk_sidecar, store


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """Real resolve_allowed_path (no stub); only ``allowed/`` is on the allow-list."""
    investigations_root = tmp_path / "investigations_root"
    investigations_root.mkdir()
    monkeypatch.setattr(store, "data_dir", lambda: investigations_root)
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    sample = allowed / "sample.bin"
    sample.write_bytes(b"\x7fELF" + os.urandom(256))
    secret = outside / "secret.bin"
    secret.write_bytes(b"\x7fELF" + b"x" * 64)
    (outside / "secret_dir").mkdir()
    return SimpleNamespace(tmp=tmp_path, allowed=allowed, outside=outside, sample=sample, secret=secret,
                           roots=[str(allowed)], investigations_root=investigations_root)


def _refusal(target: str, allowed) -> tuple[type, str]:
    with pytest.raises(OSError) as info:
        store.prepare(target, "What is this?", allowed, None)
    return type(info.value), str(info.value)


def _symlink(link: Path, to: Path) -> None:
    try:
        link.symlink_to(to, target_is_directory=to.is_dir())
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without symlink rights
        pytest.skip("symlinks unavailable")


def _no_leftover_workspaces(layout) -> None:
    root = layout.investigations_root / "investigations"
    assert not root.exists() or list(root.iterdir()) == []


def test_outside_existing_missing_and_link_targets_are_indistinguishable(layout):
    _symlink(layout.outside / "link_to_secret", layout.secret)
    _symlink(layout.outside / "link_into_allowed", layout.sample)  # outside link pointing inside
    _symlink(layout.outside / "dangling", layout.outside / "gone")
    targets = [
        layout.secret,                                   # exists (file)
        layout.outside / "secret_dir",                   # exists (folder)
        layout.outside / "missing.bin",                  # does not exist
        layout.outside / "missing" / "deeper.bin",       # parent missing too
        layout.outside / "link_to_secret",               # link to an outside file
        layout.outside / "link_into_allowed",            # link whose target is inside the list
        layout.outside / "dangling",                     # dangling link
        layout.allowed / ".." / "outside" / "secret.bin",  # lexical .. escape
    ]
    results = {_refusal(str(t), layout.roots) for t in targets}
    assert results == {(PermissionError, store.OUTSIDE_ALLOWED)}
    _no_leftover_workspaces(layout)


def test_outside_refusal_never_probes_the_target(layout, monkeypatch):
    probed: list[str] = []
    real_lstat, real_stat = os.lstat, os.stat

    def spy(fn):
        def wrapped(path, *a, **kw):
            if str(layout.outside) in os.fspath(path):
                probed.append(os.fspath(path))
            return fn(path, *a, **kw)
        return wrapped

    monkeypatch.setattr(os, "lstat", spy(real_lstat))
    monkeypatch.setattr(os, "stat", spy(real_stat))
    assert _refusal(str(layout.secret), layout.roots) == (PermissionError, store.OUTSIDE_ALLOWED)
    assert probed == []


def test_inside_link_is_still_refused(layout):
    _symlink(layout.allowed / "link.bin", layout.sample)
    assert _refusal(str(layout.allowed / "link.bin"), layout.roots) == (
        PermissionError, "Linked/reparse targets are not admitted")
    _no_leftover_workspaces(layout)


def test_inside_linked_parent_escaping_the_list_gets_the_same_message(layout):
    _symlink(layout.allowed / "linked_dir", layout.outside)
    for t in (layout.allowed / "linked_dir" / "secret.bin", layout.allowed / "linked_dir" / "missing.bin"):
        assert _refusal(str(t), layout.roots) == (PermissionError, store.OUTSIDE_ALLOWED)


def test_inside_missing_target_keeps_its_existing_error(layout):
    # prepare() has no explicit exists() check: a missing in-list target fails in fingerprint()
    # with ValueError("Target has no regular files"), as before this change.
    with pytest.raises(ValueError, match="no regular files"):
        store.prepare(str(layout.allowed / "nope.bin"), "What is this?", layout.roots, None)
    _no_leftover_workspaces(layout)


def test_empty_and_none_allow_lists_admit_nothing_as_before(layout):
    for allowed in ([], None):
        assert _refusal(str(layout.sample), allowed) == (PermissionError, "No workspace directories are configured")
        assert _refusal(str(layout.outside / "missing.bin"), allowed) == (
            PermissionError, "No workspace directories are configured")


def test_happy_path_unchanged(layout):
    row = store.prepare(str(layout.sample), "What is this?", layout.roots, "task-1")
    assert row["status"] == "prepared" and row["target"] == str(layout.sample.resolve())
    assert Path(row["snapshot"]).read_bytes() == layout.sample.read_bytes()


def test_apk_file_origin_gates_before_its_is_dir_probe(layout):
    (layout.outside / "app_dir").mkdir()
    results = set()
    for t in (layout.outside / "app_dir", layout.outside / "missing_dir", layout.outside / "x.apk"):
        with pytest.raises(OSError) as info:
            apk_sidecar.prepare_apk(str(t), "q", layout.roots, None)
        results.add((type(info.value), str(info.value)))
    assert results == {(PermissionError, store.OUTSIDE_ALLOWED)}


@pytest.mark.asyncio
async def test_api_returns_identical_refusal_for_outside_existing_missing_and_link(layout, allow_loopback_api, monkeypatch):
    _symlink(layout.outside / "link_to_secret", layout.secret)
    monkeypatch.setattr("app.api.investigations.load_settings",
                        lambda: SimpleNamespace(allowed_directories=layout.roots))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        responses = [await client.post("/api/investigations", json={"target": str(t), "question": "What is this?"})
                     for t in (layout.secret, layout.outside / "missing.bin", layout.outside / "link_to_secret")]
        assert {(r.status_code, r.text) for r in responses} == {
            (422, '{"detail":"' + store.OUTSIDE_ALLOWED + '"}')}
        ok = await client.post("/api/investigations", json={"target": str(layout.sample), "question": "What is this?"})
        assert ok.status_code == 200, ok.text


# ----- linked parent to outside (D2 #660 review 1, same gate in store.prepare) -----

def test_store_prepare_linked_parent_to_outside_never_reveals_the_leaf(layout, monkeypatch):
    _symlink(layout.allowed / "linkdir", layout.outside)
    _symlink(layout.outside / "leaf_link", layout.secret)
    linkdir = layout.allowed / "linkdir"
    targets = [linkdir / "secret.bin", linkdir / "missing.bin", linkdir / "leaf_link", linkdir / "secret_dir"]
    assert {_refusal(str(t), layout.roots) for t in targets} == {(PermissionError, store.OUTSIDE_ALLOWED)}
    probed: list[str] = []
    real_lstat = os.lstat

    def spy(path, *a, **kw):
        if os.fspath(path).endswith("leaf_link"):
            probed.append(os.fspath(path))
        return real_lstat(path, *a, **kw)

    monkeypatch.setattr(os, "lstat", spy)
    assert _refusal(str(linkdir / "leaf_link"), layout.roots) == (PermissionError, store.OUTSIDE_ALLOWED)
    assert probed == []
    _no_leftover_workspaces(layout)


def test_no_gate_error_names_a_real_path(layout):
    _symlink(layout.outside / "into_allowed", layout.sample)
    _symlink(layout.allowed / "linkdir", layout.outside)
    for t in (layout.outside / "into_allowed", layout.allowed / "linkdir" / "secret.bin"):
        _, message = _refusal(str(t), layout.roots)
        assert message == store.OUTSIDE_ALLOWED and str(layout.tmp) not in message


# ----- prepare_ffs: in-list errors name the target as typed, never its real path -----

def test_prepare_ffs_missing_target_names_the_typed_path(layout):
    (layout.allowed / "real").mkdir()
    _symlink(layout.allowed / "alias", layout.allowed / "real")
    typed = str(layout.allowed / "alias" / "nope")
    with pytest.raises(FileNotFoundError) as info:
        store.prepare_ffs(typed, "q", layout.roots, None)
    assert str(info.value) == f"Source target does not exist: {typed}" and "real" not in str(info.value)


# ----- apk_sidecar.prepare_apk (file and ffs origins) -----

def test_prepare_apk_file_origin_outside_cases_are_indistinguishable(layout):
    (layout.outside / "app_dir").mkdir()
    (layout.outside / "real.apk").write_bytes(b"PK\x03\x04")
    _symlink(layout.outside / "link.apk", layout.outside / "real.apk")
    _symlink(layout.allowed / "linkdir", layout.outside)
    targets = [layout.outside / "app_dir", layout.outside / "missing_dir", layout.outside / "real.apk",
               layout.outside / "missing.apk", layout.outside / "link.apk",
               layout.allowed / "linkdir" / "app_dir", layout.allowed / "linkdir" / "missing_dir"]
    results = set()
    for t in targets:
        with pytest.raises(OSError) as info:
            apk_sidecar.prepare_apk(str(t), "q", layout.roots, None)
        results.add((type(info.value), str(info.value)))
    assert results == {(PermissionError, store.OUTSIDE_ALLOWED)}


def test_prepare_apk_file_origin_inside_checks_unchanged(layout):
    with pytest.raises(ValueError, match="must be a .apk"):
        apk_sidecar.prepare_apk(str(layout.allowed / "missing_dir"), "q", layout.roots, None)
    _symlink(layout.allowed / "link.apk", layout.sample)
    with pytest.raises(PermissionError, match="Linked/reparse"):
        apk_sidecar.prepare_apk(str(layout.allowed / "link.apk"), "q", layout.roots, None)


def test_prepare_apk_ffs_origin_checks_the_dump_root_before_probing_it(layout, monkeypatch):
    results = set()
    for dump in (layout.outside / "secret_dir", layout.outside / "gone_dump"):
        ident = "a" * 31 + ("1" if dump.name == "secret_dir" else "2")
        monkeypatch.setattr(store, "load", lambda i, d=dump: {"id": i, "kind": "ffs", "target": str(d)})
        with pytest.raises(OSError) as info:
            apk_sidecar.prepare_apk("data/app/base.apk", "q", layout.roots, None,
                                    source_type="ffs", ffs_investigation_id=ident)
        results.add((type(info.value), str(info.value)))
    assert results == {(PermissionError, store.OUTSIDE_ALLOWED)}


# ----- HTTP routes: identical 422 bodies -----

@pytest.mark.asyncio
@pytest.mark.parametrize("route,extra", [
    ("/api/investigations", {"question": "What is this?"}),
    ("/api/investigations/ffs", {}),
    ("/api/investigations/ingest", {"background": False}),
    ("/api/investigations/apk/prepare", {"source_type": "file"}),
])
async def test_every_prepare_route_gives_the_identical_422(layout, allow_loopback_api, monkeypatch, route, extra):
    _symlink(layout.outside / "link_to_secret", layout.secret)
    _symlink(layout.allowed / "linkdir", layout.outside)
    monkeypatch.setattr("app.api.investigations.load_settings",
                        lambda: SimpleNamespace(allowed_directories=layout.roots))
    targets = [layout.secret, layout.outside / "secret_dir", layout.outside / "missing.bin",
               layout.outside / "missing_dir", layout.outside / "link_to_secret",
               layout.allowed / "linkdir" / "secret.bin", layout.allowed / "linkdir" / "missing.bin"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        responses = [await client.post(route, json={"target": str(t), **extra}) for t in targets]
    assert {(r.status_code, r.text) for r in responses} == {(422, '{"detail":"' + store.OUTSIDE_ALLOWED + '"}')}
