from app.tools.docker_tools import DockerTool
from app.tools.office import OfficeTool
from app.tools.web_fetch import WebFetchTool


async def test_docker_requires_targets():
    tool = DockerTool()
    run = await tool.execute(action="run")
    assert run.success is False
    assert "image is required" in run.error
    logs = await tool.execute(action="logs")
    assert "container is required" in logs.error
    inspect = await tool.execute(action="inspect")
    assert "container or image is required" in inspect.error


async def test_office_info_does_not_need_com():
    tool = OfficeTool()
    info = await tool.execute(app="word", action="info")
    assert info.success
    assert "available=" in info.output
    assert "Word.Application" in info.output


async def test_web_fetch_rejects_local_schemes():
    tool = WebFetchTool()
    for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/plain,hi"):
        result = await tool.execute(url=url)
        assert result.success is False
        assert "Blocked URL scheme" in result.error
