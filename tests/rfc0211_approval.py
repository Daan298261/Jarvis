"""Test helper: the owner's tap on the existing approval card for one exact self-development change.

Mints an RFC-0031 ApprovalGrant the way the UI does (park the exact change, then decide from a
trusted channel), so tests exercise the real grant validation in the tool.
"""
from __future__ import annotations

from app.policy import approval_grant as grants
from app.tools import self_development as tool_module


def isolate_grants(tmp_path, monkeypatch):
    monkeypatch.setattr(grants, "data_dir", lambda: tmp_path / "grants")
    (tmp_path / "grants").mkdir(exist_ok=True)


def owner_tap(action, task_id="t", **arguments):
    change = tool_module.pending_change({"action": action, **arguments})
    if change is None:
        return None
    target = tool_module.approval_target(change)
    action_id = grants.action_id_for("self_development", action, target, task_id=task_id)
    parked = grants.park_approval_request(action_id=action_id, tool_name="self_development", action=action,
                                          scope={}, target=target, task_id=task_id)
    outcome = grants.decide_approval_request(parked["id"], decision="allow_once", origin_channel="ui", actor="owner")
    return (outcome.get("grant") or {}).get("id")
