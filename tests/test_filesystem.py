from app.tools.filesystem import FilesystemTool


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
