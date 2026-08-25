from pathlib import Path

from app.tools.office import OfficeTool, _parse_table, office_com_available, office_library_available


def _tool(tmp_path: Path) -> OfficeTool:
    return OfficeTool(lambda: {"allowed_directories": [str(tmp_path)]})


def test_parse_table_accepts_tsv_csv_and_json():
    assert _parse_table("a\tb\n1\t2") == [["a", "b"], ["1", "2"]]
    assert _parse_table("a,b\n1,2") == [["a", "b"], ["1", "2"]]
    assert _parse_table('[{"name":"Ada","n":1},{"name":"Bob","n":2}]')[0] == ["name", "n"]


def test_office_com_is_not_claimed_on_linux():
    assert office_com_available() is False


async def test_excel_create_read_write_append_and_info(tmp_path):
    assert office_library_available("excel")
    tool = _tool(tmp_path)
    dest = tmp_path / "research.xlsx"
    created = await tool.execute(
        app="excel",
        action="create",
        path=str(dest),
        content="name\tscore\nAda\t10",
        backend="library",
    )
    assert created.success, created.error
    read = await tool.execute(app="excel", action="read", path=str(dest), backend="library")
    assert read.success
    assert "Ada" in read.output
    written = await tool.execute(
        app="excel",
        action="write",
        path=str(dest),
        content='[{"name":"Bob","score":9}]',
        backend="library",
    )
    assert written.success, written.error
    appended = await tool.execute(
        app="excel",
        action="append",
        path=str(dest),
        content="Cyd\t8",
        backend="library",
    )
    assert appended.success, appended.error
    info = await tool.execute(app="excel", action="info", path=str(dest), backend="library")
    assert info.success
    assert "backend=library" in info.output
    again = await tool.execute(app="excel", action="read", path=str(dest), backend="library")
    assert "Bob" in again.output
    assert "Cyd" in again.output


async def test_word_and_powerpoint_roundtrip(tmp_path):
    tool = _tool(tmp_path)
    docx = tmp_path / "notes.docx"
    created = await tool.execute(app="word", action="create", path=str(docx), content="Hello\nWorld", backend="library")
    assert created.success, created.error
    read = await tool.execute(app="word", action="read", path=str(docx), backend="library")
    assert "Hello" in read.output
    appended = await tool.execute(app="word", action="append", path=str(docx), content="More", backend="library")
    assert appended.success
    read2 = await tool.execute(app="word", action="read", path=str(docx), backend="library")
    assert "More" in read2.output

    pptx = tmp_path / "talk.pptx"
    slides = await tool.execute(
        app="powerpoint",
        action="create",
        path=str(pptx),
        content="Title one\n---\nTitle two",
        backend="library",
    )
    assert slides.success, slides.error
    info = await tool.execute(app="powerpoint", action="info", path=str(pptx), backend="library")
    assert info.data["slides"] == 2
    read_ppt = await tool.execute(app="powerpoint", action="read", path=str(pptx), backend="library")
    assert "Title one" in read_ppt.output


async def test_office_respects_sandbox(tmp_path):
    tool = _tool(tmp_path)
    result = await tool.execute(app="excel", action="create", path="/etc/passwd.xlsx", backend="library")
    assert result.success is False
    assert "outside allowed directories" in result.error


async def test_office_com_backend_errors_without_windows(tmp_path):
    tool = _tool(tmp_path)
    result = await tool.execute(app="word", action="info", path=str(tmp_path / "n.docx"), backend="com")
    assert result.success is False
    assert "COM is not available" in result.error
