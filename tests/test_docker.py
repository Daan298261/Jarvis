from app.tools.docker_tools import DockerTool


async def test_docker_run_logs_inspect_require_targets(monkeypatch):
    tool = DockerTool()
    monkeypatch.setattr("app.tools.docker_tools.shutil.which", lambda name: "/usr/bin/docker")
    ran = await tool.execute(action="run")
    assert ran.success is False
    assert "image is required" in ran.error
    logs = await tool.execute(action="logs")
    assert "container is required" in logs.error
    inspect = await tool.execute(action="inspect")
    assert "container or image is required" in inspect.error


async def test_docker_missing_binary():
    tool = DockerTool()
    result = await tool.execute(action="ps")
    if result.success:
        return
    assert "not installed" in result.error
