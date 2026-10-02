import os
from pathlib import Path

from app.config import LOCAL_NETWORK_SCOPE
from app.tools.filesystem import FilesystemTool, search_workspace_roots


async def test_filesystem_write_read_hash(tmp_path):
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    folder = tmp_path / "Jarvis-Test"
    created = await tool.execute(action="mkdir", path=str(folder))
    assert created.success
    written = await tool.execute(action="write", path=str(folder / "note.txt"), content="READY", create_backup=False)
    assert written.success
    read = await tool.execute(action="read", path=str(folder / "note.txt"))
    assert read.output == "READY"
    hashed = await tool.execute(action="hash", path=str(folder / "note.txt"))
    assert hashed.success and "sha256" in hashed.output


async def test_filesystem_rejects_outside_path(tmp_path):
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(action="read", path="/etc/passwd")
    assert result.success is False
    assert "outside allowed directories" in result.error


async def test_filesystem_compare_identical_and_diff(tmp_path):
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text("alpha\nbeta\n", encoding="utf-8")
    right.write_text("alpha\nbeta\n", encoding="utf-8")
    same = await tool.execute(action="compare", path=str(left), destination=str(right))
    assert same.success
    assert "identical=true" in same.output

    right.write_text("alpha\ngamma\n", encoding="utf-8")
    diff = await tool.execute(action="compare", path=str(left), destination=str(right))
    assert diff.success
    assert "identical=false" in diff.output
    assert "-beta" in diff.output
    assert "+gamma" in diff.output


async def test_filesystem_compare_rejects_outside_destination(tmp_path):
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    inside = tmp_path / "inside.txt"
    inside.write_text("ok", encoding="utf-8")
    result = await tool.execute(action="compare", path=str(inside), destination="/etc/passwd")
    assert result.success is False
    assert "outside allowed directories" in result.error


async def test_filesystem_compare_requires_destination(tmp_path):
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    path = tmp_path / "only.txt"
    path.write_text("x", encoding="utf-8")
    result = await tool.execute(action="compare", path=str(path))
    assert result.success is False
    assert "destination" in result.error


async def test_filesystem_recent_versions_finds_backups(tmp_path):
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    current = tmp_path / "note.txt"
    current.write_text("now", encoding="utf-8")
    (tmp_path / "note.txt.bak").write_text("old", encoding="utf-8")
    stamped = tmp_path / "note.txt.bak-20260824110100"
    stamped.write_text("older", encoding="utf-8")
    (tmp_path / "unrelated.txt").write_text("nope", encoding="utf-8")

    result = await tool.execute(action="recent", path=str(current))
    assert result.success
    versions = result.data["versions"]
    paths = [row["path"] for row in versions]
    assert str(current) in paths
    assert str(tmp_path / "note.txt.bak") in paths
    assert str(stamped) in paths
    assert not any(p.endswith("unrelated.txt") for p in paths)
    kinds = {row["path"]: row["kind"] for row in versions}
    assert kinds[str(current)] == "current"
    assert kinds[str(tmp_path / "note.txt.bak")] == "backup"


async def test_list_without_path_shows_every_allowed_root(tmp_path):
    extra = tmp_path / "E"
    extra.mkdir()
    homeish = tmp_path / "home"
    homeish.mkdir()
    (homeish / "inside.txt").write_text("x", encoding="utf-8")
    tool = FilesystemTool(
        lambda: {"allowed_directories": [str(homeish), str(extra), LOCAL_NETWORK_SCOPE]}
    )
    listed = await tool.execute(action="list")
    assert listed.success
    roots = listed.data["roots"]
    assert str(homeish.resolve()) in roots
    assert str(extra.resolve()) in roots
    assert listed.data["lan_shares"] is True
    assert LOCAL_NETWORK_SCOPE in listed.output
    assert "inside.txt" not in listed.output


async def test_list_with_path_still_lists_contents(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.txt").write_text("a", encoding="utf-8")
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    listed = await tool.execute(action="list", path=str(folder))
    assert listed.success
    assert "a.txt" in listed.output


async def test_search_without_path_covers_extra_volume(tmp_path):
    extra = tmp_path / "E" / "Photos"
    extra.mkdir(parents=True)
    photo = extra / "vacation.jpg"
    photo.write_bytes(b"x")
    homeish = tmp_path / "home"
    homeish.mkdir()
    (homeish / "notes.txt").write_text("hi", encoding="utf-8")
    outside = tmp_path / "secret.bin"
    outside.write_bytes(b"no")
    tool = FilesystemTool(
        lambda: {"allowed_directories": [str(homeish), str(tmp_path / "E")]}
    )
    photos = await tool.execute(action="search", pattern="*.jpg")
    assert photos.success
    assert str(photo) in photos.output
    found = await tool.execute(action="search", pattern="*")
    assert "notes.txt" in found.output
    assert "secret.bin" not in found.output


async def test_search_workspace_roots_skips_os_volume(tmp_path):
    extra = tmp_path / "usb"
    extra.mkdir()
    if os.name == "nt":
        system = str(Path.home().anchor)
        roots = search_workspace_roots([system, str(extra)])
    else:
        roots = search_workspace_roots(["/", str(extra)])
        assert Path("/") not in roots
    assert extra.resolve() in roots


async def test_search_with_path_stays_in_that_folder(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "keep.txt").write_text("k", encoding="utf-8")
    (right / "other.txt").write_text("o", encoding="utf-8")
    tool = FilesystemTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(action="search", path=str(left), pattern="*.txt")
    assert result.success
    assert "keep.txt" in result.output
    assert "other.txt" not in result.output

