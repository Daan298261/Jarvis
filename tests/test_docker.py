from app.tools.docker_tools import DockerTool


async def test_docker_run_requires_an_image():
    result = await DockerTool().execute(action="run", args="-it")
    assert result.success is False
    assert "requires an image" in (result.error or "")
