from pathlib import Path

from app.tools.docker_tools import (
    DockerTool,
    docker_argv,
    rewrite_docker_run_args,
    rewrite_volume_spec,
    split_bind_spec,
)
from app.tools.browser import BrowserTool
from app.tools import browser as browser_mod


async def test_docker_run_requires_an_image_even_when_docker_is_missing():
    result = await DockerTool().execute(action="run", args="-it")
    assert result.success is False
    assert "image" in (result.error or "").lower()


def test_split_bind_spec_keeps_windows_drive_on_host():
    host, rest = split_bind_spec(r"D:\USB\data:/app:ro")
    assert host == r"D:\USB\data"
    assert rest == ":/app:ro"
    posix = split_bind_spec("/home/owner/src:/src")
    assert posix == ("/home/owner/src", ":/src")
    assert split_bind_spec("pgdata:/var/lib/postgresql/data") is None


def test_rewrite_volume_spec_onto_extra_drive(tmp_path):
    extra = tmp_path / "E" / "data"
    extra.mkdir(parents=True)
    rewritten = rewrite_volume_spec(f"{extra}:/app:ro", [str(tmp_path)])
    assert rewritten.startswith(str(extra.resolve()))
    assert rewritten.endswith(":/app:ro")


def test_rewrite_docker_run_args_bind_mounts(tmp_path):
    extra = tmp_path / "D" / "proj"
    extra.mkdir(parents=True)
    args = rewrite_docker_run_args(
        f"-v {extra}:/work --mount type=bind,source={extra},target=/src",
        [str(tmp_path)],
    )
    assert str(extra.resolve()) in args
    assert "/work" in args
    assert "target=/src" in args


async def test_docker_build_uses_extra_drive_context(tmp_path):
    extra = tmp_path / "E" / "app"
    extra.mkdir(parents=True)
    (extra / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    tool = DockerTool(lambda: {"allowed_directories": [str(tmp_path)]})
    argv, err = docker_argv("build", {"path": str(extra)})
    assert err == ""
    assert argv == ["build", str(extra)]
    resolved = tool._build_path(str(extra))
    assert Path(resolved) == extra.resolve()
    blocked = await tool.execute(action="build", path="/etc")
    assert blocked.success is False
    assert "outside allowed directories" in (blocked.error or "")


async def test_docker_build_omitted_path_uses_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))
    tool = DockerTool(lambda: {"allowed_directories": [str(tmp_path)]})
    assert Path(tool._build_path(None)) == docs.resolve()


async def test_docker_build_without_path_refuses_foreign_cwd(tmp_path):
    tool = DockerTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(action="build")
    assert result.success is False
    assert "path is required" in (result.error or "")


async def test_browser_close_clears_pages_without_launching():
    browser_mod._pages = [object()]
    browser_mod._page = object()
    browser_mod._browser = object()
    browser_mod._context = None
    browser_mod._playwright = None
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="close")
    assert result.success
    assert browser_mod._pages == []
    assert browser_mod._page is None
    assert browser_mod._browser is None
    assert "closed" in result.output.lower()



async def test_browser_close_clears_pages_without_launching():
    browser_mod._pages = [object()]
    browser_mod._page = object()
    browser_mod._browser = object()
    browser_mod._context = None
    browser_mod._playwright = None
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="close")
    assert result.success
    assert browser_mod._pages == []
    assert browser_mod._page is None
    assert browser_mod._browser is None
    assert "closed" in result.output.lower()
