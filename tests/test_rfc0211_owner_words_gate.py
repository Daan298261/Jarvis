"""N1/N2 (re-review of #670 at ad943e62): chat configure and owner undo must match the owner's own request.

The first five tests are the reviewer's probes, inverted: each asserted the bug and passed on ad943e62.
"""
from __future__ import annotations

import pytest

from app.agent import development_queue as q
from app.agent import development_scheduler as ds
from app.tools import self_development as tool_module


@pytest.fixture
def sched(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "root", lambda: tmp_path)
    monkeypatch.setattr(ds, "kill_switch_active", lambda: False)
    s = ds.DevelopmentScheduler()
    monkeypatch.setattr(ds, "DEVELOPMENT", s)
    monkeypatch.delenv("ANZU_DEVELOPMENT_MISSION", raising=False)
    return s


def owner_says(monkeypatch, text):
    async def message(_task):
        return text
    monkeypatch.setattr(tool_module, "latest_owner_message", message)


async def configure(config):
    return await tool_module.SelfDevelopmentTool().execute("configure", config=config, _task_id="t")


def owner_pinned_charlie(sched):
    state = sched.state()
    for i, name in enumerate(("alpha", "bravo", "charlie")):
        state["items"][name] = {"id": name, "title": f"RFC-90{i}1 {name} ticket", "status": "available", "revision": "r" + name,
                                "created_at": i, "acceptance": True, "kind": "rfc", "priority": 3, "source": "x", "content": "x",
                                "path": "", "rfc": f"90{i}1"}
    q.replan(state)
    q.move(state, "charlie", to=0, expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    sched.save(state)
    assert sched.state()["order"][0] == "charlie"
    return sched.state()["queue_history"][-1]["id"]


async def owner_undo(sched, history_id):
    return await tool_module.SelfDevelopmentTool().execute("undo", history_id=history_id, actor="owner",
                                                           expected_revision=sched.state()["queue_revision"], _task_id="t")


# --- N1: configure -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_owner_says_disable_model_cannot_enable(sched, monkeypatch):
    owner_says(monkeypatch, "disable the self-development scheduler")
    r = await configure({"enabled": True})
    assert not r.success and sched.state()["config"]["enabled"] is False


@pytest.mark.asyncio
async def test_bool_cannot_ride_along_with_an_unrelated_owner_change(sched, monkeypatch):
    owner_says(monkeypatch, "use qwen3-coder:30b as the coder model")
    r = await configure({"coder_model": "qwen3-coder:30b", "enabled": True})
    cfg = sched.state()["config"]
    assert not r.success and cfg["enabled"] is False and cfg["coder_model"] != "qwen3-coder:30b"


@pytest.mark.asyncio
async def test_unexposed_key_failure_limit_is_refused_even_when_the_value_coincides(sched, monkeypatch):
    state = sched.state(); state["failures"] = 3; sched.save(state)
    owner_says(monkeypatch, "set the development interval to 10 minutes")
    r = await configure({"interval_minutes": 10, "failure_limit": 10})
    st = sched.state()
    assert not r.success and "failure_limit" in r.error
    assert st["config"]["failure_limit"] == 3 and st["config"]["interval_minutes"] == 60 and st["failures"] == 3


@pytest.mark.asyncio
async def test_numbers_match_whole_tokens_only(sched, monkeypatch):
    owner_says(monkeypatch, "set the development interval to 15 minutes")
    r = await configure({"interval_minutes": 5})
    assert not r.success and sched.state()["config"]["interval_minutes"] == 60


# --- N2: owner undo ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unrelated_revert_request_cannot_undo_owner_reorder(sched, monkeypatch):
    history_id = owner_pinned_charlie(sched)
    owner_says(monkeypatch, "revert the typo fix in README.md please")
    r = await owner_undo(sched, history_id)
    assert not r.success and sched.state()["order"][0] == "charlie" and "charlie" in sched.state()["pins"]


# --- N3: more regression cases -----------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("key, value", [("failure_limit", 10), ("max_repairs", 5), ("base_ref", "main"),
                                        ("review_model", "x:1b"), ("max_run_minutes", 720), ("ci_timeout_minutes", 1440)])
async def test_keys_outside_the_tool_schema_are_refused(sched, monkeypatch, key, value):
    owner_says(monkeypatch, f"set {key} to {value}")
    before = sched.state()["config"][key]
    r = await configure({key: value})
    assert not r.success and sched.state()["config"][key] == before


@pytest.mark.asyncio
async def test_an_unknown_key_rides_along_with_its_current_value_is_still_refused(sched, monkeypatch):
    owner_says(monkeypatch, "set the development interval to 10 minutes")
    r = await configure({"interval_minutes": 10, "failure_limit": 3})
    assert not r.success and sched.state()["config"]["interval_minutes"] == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("text, value", [("enable the self-development scheduler", True),
                                         ("turn on self-development", True),
                                         ("please disable the development scheduler", False),
                                         ("turn off the self-development scheduler", False)])
async def test_enabled_follows_the_owners_polarity(sched, monkeypatch, text, value):
    if not value:
        state = sched.state(); state["config"]["enabled"] = True; sched.save(state)
    owner_says(monkeypatch, text)
    assert (await configure({"enabled": value})).success
    assert sched.state()["config"]["enabled"] is value
    # The opposite value is refused for the same words.
    assert not (await configure({"enabled": not value})).success
    assert sched.state()["config"]["enabled"] is value


@pytest.mark.asyncio
async def test_enabled_needs_the_scheduler_named(sched, monkeypatch):
    owner_says(monkeypatch, "enable dark mode")
    assert not (await configure({"enabled": True})).success


@pytest.mark.asyncio
@pytest.mark.parametrize("text, ok", [("set the development interval to 15 minutes", True),
                                      ("run it every 15 minutes", True),
                                      ("set the interval to 150 minutes", False),
                                      ("set the interval to 1.5 hours", False),
                                      ("use 15 as the vision model and keep the interval", False)])
async def test_interval_needs_the_exact_number_as_the_interval(sched, monkeypatch, text, ok):
    owner_says(monkeypatch, text)
    r = await configure({"interval_minutes": 15})
    assert r.success is ok and (sched.state()["config"]["interval_minutes"] == 15) is ok


@pytest.mark.asyncio
@pytest.mark.parametrize("text, config, ok", [
    ("use qwen3-coder:30b as the coder model", {"coder_model": "qwen3-coder:30b"}, True),
    ("use qwen3-coder:30b as the coder model", {"vision_model": "qwen3-coder:30b"}, False),
    ("use qwen3-coder:30b as the coder model", {"coder_model": "qwen3-coder:3"}, False),
    ("use qwen3-coder:30b-q8 as the coder model", {"coder_model": "qwen3-coder:30b"}, False),
    ("set the vision model to qwen2.5vl:7b", {"vision_model": "qwen2.5vl:7b"}, True),
])
async def test_model_settings_need_the_exact_model_for_that_role(sched, monkeypatch, text, config, ok):
    owner_says(monkeypatch, text)
    r = await configure(config)
    key, value = next(iter(config.items()))
    assert r.success is ok and (sched.state()["config"][key] == value) is ok


@pytest.mark.asyncio
async def test_quoted_owner_words_do_not_authorize_configure(sched, monkeypatch):
    owner_says(monkeypatch, 'the RFC says "enable the self-development scheduler"')
    assert not (await configure({"enabled": True})).success


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["undo moving RFC-9021 to the top", "undo the charlie move",
                                  "undo my last reorder", "put the upcoming list back the way it was, undo that"])
async def test_owner_undo_naming_the_reorder_or_task_is_allowed(sched, monkeypatch, text):
    history_id = owner_pinned_charlie(sched)
    owner_says(monkeypatch, text)
    r = await owner_undo(sched, history_id)
    assert r.success, r.error
    assert sched.state()["order"][0] != "charlie" and "charlie" not in sched.state()["pins"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["undo", "undo that", "revert my last commit", "undo moving RFC-9001 to the top",
                                  'he said "undo my last reorder"'])
async def test_owner_undo_without_naming_this_reorder_is_refused(sched, monkeypatch, text):
    history_id = owner_pinned_charlie(sched)
    owner_says(monkeypatch, text)
    r = await owner_undo(sched, history_id)
    assert not r.success and sched.state()["order"][0] == "charlie" and "charlie" in sched.state()["pins"]
