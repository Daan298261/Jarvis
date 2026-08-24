from app.config import AppSettings
from app.inference.manager import resolve_vision


def test_lazy_vision_defaults_off_until_requested():
    settings = AppSettings()
    assert settings.inference.vision == "lazy"
    assert resolve_vision(settings) is False
    assert resolve_vision(settings, True) is True


def test_always_and_off_override_the_request():
    always = AppSettings(inference={"vision": "always"})
    off = AppSettings(inference={"vision": "off"})
    assert resolve_vision(always, False) is True
    assert resolve_vision(off, True) is False
