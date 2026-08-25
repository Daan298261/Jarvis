from pathlib import Path

from app.inference.profiles import resolve_profile
from app.inference.vision import messages_need_vision, mmproj_args, should_load_vision, with_vision
from app.providers.base import ChatMessage


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


def test_messages_need_vision_only_for_image_parts():
    text = ChatMessage(role="user", content="describe the desktop")
    image = ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": "what is on screen?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
        ],
    )
    assert messages_need_vision([text]) is False
    assert messages_need_vision([text, image]) is True
