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
