import pytest

from app.tools.docker_tools import DockerTool


@pytest.mark.asyncio
async def test_docker_run_requires_an_image():
    result = await DockerTool().execute(action="run", args="-d")
    assert result.success is False
    assert "requires an image" in (result.error or "")


@pytest.mark.asyncio
async def test_docker_logs_and_inspect_require_a_target():
    logs = await DockerTool().execute(action="logs")
    inspect = await DockerTool().execute(action="inspect")
    assert logs.success is False
    assert "requires a container" in (logs.error or "")
    assert inspect.success is False
    assert "requires a container or image" in (inspect.error or "")
