from pathlib import Path

from app.tools.screenshot import screenshot_dest


def test_screenshot_dest_defaults_to_pictures(tmp_path, monkeypatch):
    pictures = tmp_path / "Pictures"
    pictures.mkdir()
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))
    dest = screenshot_dest(allowed=[str(tmp_path)])
    assert dest.parent == pictures
    assert dest.name.startswith("screen-")
    assert dest.suffix == ".png"


def test_screenshot_dest_extra_drive(tmp_path):
    extra = tmp_path / "E" / "Captures"
    extra.mkdir(parents=True)
    dest = screenshot_dest(str(extra), allowed=[str(tmp_path)])
    assert dest.parent == extra
    assert dest.suffix == ".png"


def test_screenshot_dest_rejects_outside_workspace(tmp_path):
    import pytest

    with pytest.raises(PermissionError):
        screenshot_dest("/etc/jarvis-screen.png", allowed=[str(tmp_path)])
