from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import LOCAL_NETWORK_SCOPE, default_allowed_directories
from app.policy.computer_permissions import (
    apply_grant, evaluate_permission, evaluate_tool_permissions,
    reset_computer_permission_state,
)
from app.tools.safety import _private_lan_unc, resolve_allowed_path


def test_private_unc_host_classification():
    assert _private_lan_unc(r"\\nas.local\share\game.exe")
    assert _private_lan_unc(r"\\192.168.1.12\media\game.exe")
    assert _private_lan_unc(r"\\nas\media\game.exe")
    assert not _private_lan_unc(r"\\8.8.8.8\share\game.exe")
    assert not _private_lan_unc(r"\\public.example.com\share\game.exe")


def test_owner_scope_covers_steam_and_local_shares(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows drive and UNC authorization")
    allowed = default_allowed_directories()
    assert LOCAL_NETWORK_SCOPE in allowed
    steam = Path(Path.home().anchor) / "Program Files (x86)" / "Steam" / "steam.exe"
    assert resolve_allowed_path(str(steam), allowed) == steam.resolve()
    share = r"\\nas.local\games\steam.exe"
    assert str(resolve_allowed_path(share, allowed)).lower() == share.lower()
    with pytest.raises(PermissionError):
        resolve_allowed_path(r"\\8.8.8.8\share\game.exe", allowed)
    with pytest.raises(PermissionError):
        resolve_allowed_path(share, [str(tmp_path)])
    with pytest.raises(PermissionError):
        resolve_allowed_path(str(steam), [str(tmp_path)])


def test_local_network_default_is_allowed_but_explicit_deny_wins(tmp_path, monkeypatch):
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    assert evaluate_permission("network.local").status == "allow"
    assert evaluate_tool_permissions("web_fetch", {"url": "http://nas.local/status"}).status == "allow"
    assert evaluate_tool_permissions("web_fetch", {"url": "http://nas/status"}).status == "allow"
    assert evaluate_permission("network.internet").status == "ask"
    assert evaluate_tool_permissions("filesystem", {"path": r"\\nas.local\share\x"}).status == "allow"
    assert evaluate_tool_permissions("web_fetch", {"url": "https://example.com/?next=nas.local"}).status == "ask"
    apply_grant("network.local", "deny")
    assert evaluate_permission("network.local").status == "deny"
    assert evaluate_tool_permissions("filesystem", {"path": r"\\nas.local\share\x"}).status == "deny"
