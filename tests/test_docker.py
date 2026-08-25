from app.tools.docker_tools import docker_argv
from app.tools.docker_tools import DockerTool


def test_run_requires_image():
    args, error = docker_argv("run", {})
    assert args is None
    assert "image is required" in error


def test_logs_requires_container():
    args, error = docker_argv("logs", {"image": "nginx"})
    assert args is None
    assert "container is required" in error


def test_inspect_requires_target():
    args, error = docker_argv("inspect", {})
    assert args is None
    assert "container or image" in error


def test_run_keeps_image_and_optional_args():
    args, error = docker_argv("run", {"image": "alpine:3", "args": "-e FOO=1"})
    assert error == ""
    assert args == ["run", "--rm", "-e", "FOO=1", "alpine:3"]


def test_ps_and_images_need_no_target():
    assert docker_argv("ps", {})[0] == ["ps", "-a"]
    assert docker_argv("images", {})[0] == ["images"]


async def test_docker_tool_rejects_run_without_image_even_if_docker_missing():
    result = await DockerTool().execute(action="run")
    assert result.success is False
    assert "image is required" in result.error
