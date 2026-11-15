"""prepare_ffs checks the allowed folders before any existence/link probe (follow-up to #651, D2 review).

Every target outside the allow-list must fail with the same PermissionError (type and message),
whether it exists, is missing, or is a link, so a caller cannot learn anything about paths outside
the owner's allowed folders. Inside the allow-list the link refusal and FileNotFoundError stay.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.main import app
from app.reverse_engineering import store


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
    dump = allowed / "dump"
    dump.mkdir()
    (dump / "a.bin").write_bytes(os.urandom(512))
    secret = outside / "secret_dump"
    secret.mkdir()
    (secret / "b.bin").write_bytes(b"x" * 64)
    return SimpleNamespace(tmp=tmp_path, allowed=allowed, outside=outside, dump=dump, secret=secret,
                           roots=[str(allowed)])


def _refusal(target: str, allowed: list[str]) -> tuple[type, str]:
    with pytest.raises(OSError) as info:
        store.prepare_ffs(target, "q", allowed, None)
    return type(info.value), str(info.value)


def _symlink(link: Path, to: Path) -> None:
    try:
        link.symlink_to(to, target_is_directory=to.is_dir())
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without symlink rights
        pytest.skip("symlinks unavailable")


def test_outside_existing_missing_and_link_targets_are_indistinguishable(layout):
    _symlink(layout.outside / "link_to_secret", layout.secret)
    _symlink(layout.outside / "link_into_allowed", layout.dump)  # an outside link that points inside
    _symlink(layout.outside / "dangling", layout.outside / "gone")
    targets = [
        layout.secret,                               # exists (folder)
        layout.secret / "b.bin",                     # exists (file)
        layout.outside / "missing",                  # does not exist
        layout.outside / "missing" / "deeper",       # parent does not exist either
        layout.outside / "link_to_secret",           # link to an outside folder
        layout.outside / "link_into_allowed",        # link whose target is inside the allow-list
        layout.outside / "dangling",                 # dangling link
        layout.allowed / ".." / "outside" / "secret_dump",  # lexical .. escape
    ]
    results = {_refusal(str(t), layout.roots) for t in targets}
    assert results == {(PermissionError, store.FFS_OUTSIDE_ALLOWED)}
    assert not any(p.name != "investigations" for p in (layout.tmp / "investigations_root").iterdir())


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
    assert _refusal(str(layout.secret), layout.roots) == (PermissionError, store.FFS_OUTSIDE_ALLOWED)
    assert probed == []


def test_inside_link_is_still_refused(layout):
    _symlink(layout.allowed / "link", layout.dump)
    assert _refusal(str(layout.allowed / "link"), layout.roots) == (
        PermissionError, "Linked/reparse target is not admitted")


def test_inside_linked_parent_escaping_the_list_is_refused_with_the_same_message(layout):
    _symlink(layout.allowed / "linked_dir", layout.outside)
    for t in (layout.allowed / "linked_dir" / "secret_dump", layout.allowed / "linked_dir" / "missing"):
        assert _refusal(str(t), layout.roots) == (PermissionError, store.FFS_OUTSIDE_ALLOWED)


def test_inside_missing_target_is_still_file_not_found(layout):
    kind, message = _refusal(str(layout.allowed / "nope"), layout.roots)
    assert kind is FileNotFoundError and "does not exist" in message


def test_empty_allow_list_admits_nothing(layout):
    assert _refusal(str(layout.dump), []) == (PermissionError, "No workspace directories are configured")
    assert _refusal(str(layout.outside / "missing"), []) == (PermissionError, "No workspace directories are configured")


def test_happy_path_unchanged(layout):
    row = store.prepare_ffs(str(layout.dump), "q", layout.roots, "task-1")
    assert row["kind"] == "ffs" and row["status"] == "prepared" and row["source_type"] == "folder"
    assert row["target"] == row["snapshot"] == str(layout.dump.resolve())


def test_allowed_none_trusted_callers_unchanged(layout):
    row = store.prepare_ffs(str(layout.secret), "q", None, None)
    assert row["target"] == str(layout.secret.resolve())
    _symlink(layout.outside / "link", layout.secret)
    with pytest.raises(PermissionError, match="Linked/reparse"):
        store.prepare_ffs(str(layout.outside / "link"), "q", None, None)


@pytest.mark.asyncio
async def test_api_returns_identical_refusal_for_outside_existing_missing_and_link(layout, allow_loopback_api, monkeypatch):
    _symlink(layout.outside / "link_to_secret", layout.secret)
    monkeypatch.setattr("app.api.investigations.load_settings",
                        lambda: SimpleNamespace(allowed_directories=layout.roots))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        responses = [await client.post("/api/investigations/ffs", json={"target": str(t)})
                     for t in (layout.secret, layout.outside / "missing", layout.outside / "link_to_secret")]
        bodies = {(r.status_code, r.text) for r in responses}
        assert bodies == {(422, '{"detail":"' + store.FFS_OUTSIDE_ALLOWED + '"}')}
        ok = await client.post("/api/investigations/ffs", json={"target": str(layout.dump)})
        assert ok.status_code == 200, ok.text


def test_linked_parent_to_outside_never_reveals_the_outside_leaf(layout, monkeypatch):
    """D2 #660 review: allowed/linkdir -> /outside must not lstat /outside/<leaf> before refusing."""
    _symlink(layout.allowed / "linkdir", layout.outside)
    _symlink(layout.outside / "leaf_link", layout.secret)
    _symlink(layout.outside / "leaf_dangling", layout.outside / "gone")
    (layout.outside / "sub").mkdir()
    linkdir = layout.allowed / "linkdir"
    targets = [linkdir / "secret_dump", linkdir / "missing", linkdir / "leaf_link", linkdir / "leaf_dangling",
               linkdir / "sub" / ".." / "leaf_link", linkdir / "sub" / "missing"]
    results = {_refusal(str(t), layout.roots) for t in targets}
    assert results == {(PermissionError, store.FFS_OUTSIDE_ALLOWED)}

    probed: list[str] = []
    real_lstat = os.lstat

    def spy(path, *a, **kw):
        if os.fspath(path).endswith("leaf_link"):
            probed.append(os.fspath(path))
        return real_lstat(path, *a, **kw)

    monkeypatch.setattr(os, "lstat", spy)
    assert _refusal(str(linkdir / "leaf_link"), layout.roots) == (PermissionError, store.FFS_OUTSIDE_ALLOWED)
    assert probed == []


def test_allowed_root_itself_and_in_list_linked_parent_staying_inside_are_admitted(layout):
    row = store.prepare_ffs(str(layout.allowed), "q", layout.roots, None)  # the root needs no parent check
    assert row["target"] == str(layout.allowed.resolve())
    _symlink(layout.allowed / "alias", layout.allowed / "inner")
    (layout.allowed / "inner").mkdir()
    (layout.allowed / "inner" / "d").mkdir()
    (layout.allowed / "inner" / "d" / "f.bin").write_bytes(b"x")
    row = store.prepare_ffs(str(layout.allowed / "alias" / "d"), "q", layout.roots, None)
    assert row["target"] == str((layout.allowed / "inner" / "d").resolve())


@pytest.mark.asyncio
async def test_api_linked_parent_to_outside_gives_the_identical_422(layout, allow_loopback_api, monkeypatch):
    _symlink(layout.allowed / "linkdir", layout.outside)
    _symlink(layout.outside / "leaf_link", layout.secret)
    monkeypatch.setattr("app.api.investigations.load_settings",
                        lambda: SimpleNamespace(allowed_directories=layout.roots))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        targets = [layout.secret, layout.outside / "missing", layout.allowed / "linkdir" / "leaf_link",
                   layout.allowed / "linkdir" / "secret_dump", layout.allowed / "linkdir" / "missing"]
        responses = [await client.post("/api/investigations/ffs", json={"target": str(t)}) for t in targets]
        assert {(r.status_code, r.text) for r in responses} == {
            (422, '{"detail":"' + store.FFS_OUTSIDE_ALLOWED + '"}')}


def _dotdot_layout(layout):
    """D2 #660 review 2: allowed/linkdir -> /outside/a/b, so allowed/linkdir/.. is /outside/a for the OS."""
    a = layout.outside / "a"
    (a / "b").mkdir(parents=True)
    _symlink(layout.allowed / "linkdir", a / "b")
    (a / "existing_dir").mkdir()
    (a / "existing.bin").write_bytes(b"x")
    _symlink(a / "leaf_link", layout.secret)
    _symlink(a / "dangling", a / "gone")
    _symlink(a / "root_link", layout.allowed)  # an outside link that points at the allowed root
    via = str(layout.allowed / "linkdir") + os.sep + ".." + os.sep
    if Path(via).resolve() != a.resolve():
        pytest.skip("filesystem normalizes '..' before traversing the symlink (Win32 semantics)")
    return [via + name for name in ("leaf_link", "missing", "existing.bin", "existing_dir", "dangling",
                                    "root_link", "missing" + os.sep + "deeper")] + [
        via + "..", via + ".." + os.sep + "secret_dump", via + "b" + os.sep + ".." + os.sep + "leaf_link"]


def test_dotdot_through_an_outside_link_is_judged_like_the_os(layout, monkeypatch):
    targets = _dotdot_layout(layout)
    assert {_refusal(t, layout.roots) for t in targets} == {(PermissionError, store.FFS_OUTSIDE_ALLOWED)}
    probed: list[str] = []
    real_lstat = os.lstat

    def spy(path, *a, **kw):
        if os.path.basename(os.fspath(path)) in {"leaf_link", "root_link", "dangling"}:
            probed.append(os.fspath(path))
        return real_lstat(path, *a, **kw)

    monkeypatch.setattr(os, "lstat", spy)
    for t in targets:
        _refusal(t, layout.roots)
    assert probed == []


@pytest.mark.asyncio
async def test_api_dotdot_through_an_outside_link_gives_the_identical_422(layout, allow_loopback_api, monkeypatch):
    targets = _dotdot_layout(layout)
    monkeypatch.setattr("app.api.investigations.load_settings",
                        lambda: SimpleNamespace(allowed_directories=layout.roots))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        responses = [await client.post("/api/investigations/ffs", json={"target": t}) for t in targets]
    assert {(r.status_code, r.text) for r in responses} == {(422, '{"detail":"' + store.FFS_OUTSIDE_ALLOWED + '"}')}


def test_dotdot_that_stays_inside_is_still_admitted(layout):
    (layout.allowed / "x" / "y").mkdir(parents=True)
    row = store.prepare_ffs(str(layout.allowed / "x" / "y" / ".." / ".." / "dump"), "q", layout.roots, None)
    assert row["target"] == str(layout.dump.resolve())
    row = store.prepare_ffs(str(layout.allowed / "x" / ".."), "q", layout.roots, None)
    assert row["target"] == str(layout.allowed.resolve())
