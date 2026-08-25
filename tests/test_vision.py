from pathlib import Path

from app.inference.profiles import resolve_profile
from app.inference.vision import mmproj_args, should_load_vision, with_vision


def test_vision_stays_off_for_ordinary_tasks():
    assert should_load_vision("filesystem") is False
    assert should_load_vision("software engineering") is False
    assert should_load_vision("mixed") is False


def test_vision_loads_for_screenshot_and_gui_work():
    assert should_load_vision("multimodal") is True
    assert should_load_vision("windows gui") is True
    assert should_load_vision("filesystem", force=True) is True


def test_mmproj_args_omitted_unless_vision_and_file_exist(tmp_path):
    profile = resolve_profile("balanced")
    missing = tmp_path / "missing.gguf"
    present = tmp_path / "mmproj-F16.gguf"
    present.write_bytes(b"gguf")

    assert mmproj_args(profile, present) == []
    assert mmproj_args(with_vision(profile, True), missing) == []
    args = mmproj_args(with_vision(profile, True), present)
    assert args[:2] == ["--mmproj", str(present)]
    assert "--image-min-tokens" in args
