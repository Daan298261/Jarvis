from __future__ import annotations

from app.diagnostics import redact_mapping


def test_redacts_secret_keys_recursively():
    payload = {
        "hostname": "box",
        "api_key": "secret-value",
        "nested": {"auth_token": "tok", "port": 4780},
        "private_key_path": "/tmp/x",
        "items": [{"password": "x"}, {"ok": 1}],
    }
    out = redact_mapping(payload)
    assert out["hostname"] == "box"
    assert out["api_key"] == "[redacted]"
    assert out["nested"]["auth_token"] == "[redacted]"
    assert out["nested"]["port"] == 4780
    assert out["private_key_path"] == "[redacted]"
    assert out["items"][0]["password"] == "[redacted]"
    assert out["items"][1]["ok"] == 1
