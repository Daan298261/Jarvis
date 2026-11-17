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


def owner_tap(action, **arguments):
    """The owner's tap on the approval card for exactly this change (none when there is nothing to approve).

    The wording tests below run with the tap given, so they show the refuse-only word pre-filter
    still refuses even when the owner approved the card.
    """
    if getattr(tool_module, "pending_change", None) is None or tool_module.pending_change({"action": action, **arguments}) is None:
        return None
    return tap(action, **arguments)


async def configure(config):
    return await tool_module.SelfDevelopmentTool().execute("configure", config=config, _task_id="t",
                                                           _grant_id=owner_tap("configure", config=config))


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
    args = {"history_id": history_id, "actor": "owner", "expected_revision": sched.state()["queue_revision"]}
    return await tool_module.SelfDevelopmentTool().execute("undo", **args, _task_id="t", _grant_id=owner_tap("undo", **args))


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


# --- N4: a run needs the owner to name the task it starts -------------------------------------

def charlie_queued(sched, monkeypatch):
    """charlie is queued and next; scan and launch are recorded instead of starting a worker."""
    owner_pinned_charlie(sched)
    state = sched.state()
    state["items"]["charlie"].update(status="queued", approved_revision="rcharlie")
    sched.save(state)
    assert q.next_eligible(sched.state(), automatic=False)[0]["id"] == "charlie"
    calls = []
    async def scan():
        return {}
    async def launch(**kwargs):
        calls.append(kwargs)
        return {}
    monkeypatch.setattr(sched, "scan", scan)
    monkeypatch.setattr(sched, "launch", launch)
    return calls


async def run(item_id=""):
    return await tool_module.SelfDevelopmentTool().execute("run", item_id=item_id, _task_id="t",
                                                           _grant_id=owner_tap("run", item_id=item_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("text, item_id", [
    ("start this task", ""), ("start this task", "charlie"), ("run it", ""), ("go ahead", ""),
    ("start the development mission", ""), ("kick off the next ticket", ""),
    ("start RFC-9001", ""), ("run alpha now", ""), ("start RFC-9001 as a development task", "charlie"),
    ('start the development mission for "RFC-9021"', ""), ("start the mission for `charlie`", ""),
    ("> run RFC-9021\nstart the development task", ""),
    ("run RFC-9021", "alpha"),  # the model asks for a different task than the owner named
])
async def test_run_without_the_owner_naming_the_target_is_refused(sched, monkeypatch, text, item_id):
    calls = charlie_queued(sched, monkeypatch)
    owner_says(monkeypatch, text)
    r = await run(item_id)
    assert not r.success and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text, item_id", [
    ("run charlie", ""), ("start RFC-9021", ""), ("please start rfc 9021 now", "charlie"),
    ("start the RFC-9021 charlie ticket", ""), ("kick off RFC 9021", "charlie"),
])
async def test_run_naming_the_target_is_allowed_and_pins_it(sched, monkeypatch, text, item_id):
    calls = charlie_queued(sched, monkeypatch)
    owner_says(monkeypatch, text)
    r = await run(item_id)
    assert r.success, r.error
    # The launch is bound to the task the owner named, so a queue change in between can't swap it.
    assert calls == [{"expected": "charlie"}]


@pytest.mark.asyncio
async def test_launch_refuses_when_the_next_task_is_not_the_one_the_owner_named(sched, monkeypatch):
    owner_pinned_charlie(sched)
    state = sched.state()
    state["items"]["charlie"].update(status="queued", approved_revision="rcharlie")
    sched.save(state)
    with pytest.raises(ValueError, match="not the next"):
        await sched.launch(expected="alpha")
    assert sched.state()["runs"] == []


# --- Final review at e1f8ff38: F1 negation, F2 interval binding, CoS ruling on "#N" for run ----

@pytest.mark.asyncio
@pytest.mark.parametrize("text, value", [
    ("don't enable the self-development scheduler", True),
    ("never turn on the scheduler", True),
    ("I don't want you to enable the scheduler", True),
    ("no need to turn on self-development", True),
    ("do not disable the scheduler", False),
    ("please don't turn off the self-development scheduler", False),
    ("never switch off the scheduler", False),
])
async def test_negated_on_off_request_is_refused_both_ways(sched, monkeypatch, text, value):
    # F1: a negated request never authorizes a change; when unsure, refuse.
    state = sched.state(); state["config"]["enabled"] = not value; sched.save(state)
    owner_says(monkeypatch, text)
    r = await configure({"enabled": value})
    assert not r.success and sched.state()["config"]["enabled"] is (not value)


@pytest.mark.asyncio
async def test_a_negation_in_another_clause_also_refuses_under_fail_closed(sched, monkeypatch):
    # Was allowed after F1 (clause-scoped); CoS's fail-closed ruling refuses any negation anywhere.
    owner_says(monkeypatch, "don't wait for me, enable the self-development scheduler")
    assert not (await configure({"enabled": True})).success


@pytest.mark.asyncio
@pytest.mark.parametrize("text, value", [
    ("set the interval to 30 minutes, I'll be back in 5 minutes", 5),
    ("set the interval to 30 minutes, I'll be back in 5 minutes", 30),
    ("run for 30 minutes, keep the interval", 30),
    ("change the interval from 60 to 15", 15),
    ("every 15 minutes check the build, set the interval to 30", 15),
])
async def test_interval_number_must_be_bound_to_the_interval_and_unambiguous(sched, monkeypatch, text, value):
    # F2: the number must be the object of the interval phrase, and the only number in the request.
    owner_says(monkeypatch, text)
    r = await configure({"interval_minutes": value})
    assert not r.success and sched.state()["config"]["interval_minutes"] == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["set the interval of 15 minutes", "make the interval 15", "set interval: 15 min"])
async def test_interval_phrasings_bound_to_the_number_are_allowed(sched, monkeypatch, text):
    owner_says(monkeypatch, text)
    r = await configure({"interval_minutes": 15})
    assert r.success, r.error


@pytest.mark.asyncio
@pytest.mark.parametrize("text, item_id", [("run the tests on PR #9021", ""), ("kick off #9021", "charlie"),
                                           ("start #9021 now", "")])
async def test_hash_number_does_not_name_an_rfc_for_a_run(sched, monkeypatch, text, item_id):
    # CoS ruling: for a run only "RFC-N", "RFC N", the task id or the title name the task.
    calls = charlie_queued(sched, monkeypatch)
    owner_says(monkeypatch, text)
    r = await run(item_id)
    assert not r.success and calls == []


def test_hash_number_still_names_the_task_for_move_and_queue():
    item = {"id": "charlie", "title": "RFC-9021 charlie ticket", "rfc": "9021"}
    assert tool_module.owner_asked("move #9021 to the top", "move", item=item) == ""
    assert tool_module.owner_asked("queue #9021", "queue", item=item) == ""
    assert tool_module.owner_asked("run #9021", "run", item=item) != ""


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False])
async def test_both_directions_in_one_request_is_ambiguous(sched, monkeypatch, value):
    state = sched.state(); state["config"]["enabled"] = not value; sched.save(state)
    owner_says(monkeypatch, "enable the self-development scheduler, actually no, disable the scheduler")
    assert not (await configure({"enabled": value})).success


# --- F4: task ids match as whole tokens, never as substrings; RFC numbers by whole number --------

HEX = "b9e2d47c1a0f3e29bb11cd13"
HEX_ITEM = {"id": HEX, "title": "RFC-9011 Self-development scheduler", "rfc": "9011"}
CHARLIE = {"id": "charlie", "title": "RFC-9021 charlie ticket", "rfc": "9021"}


def gate_says(text, action, item):
    """'' when the gate accepts ``text`` as naming ``item`` for ``action``."""
    if action == "undo":
        return "" if tool_module.owner_asked(text, "undo", moved=[item]) == "" else "refused"
    verb = {"run": "start", "move": "move", "queue": "queue"}[action]
    suffix = " to the top" if action == "move" else ""
    return tool_module.owner_asked(f"{verb} {text}{suffix}", action, item=item)


@pytest.mark.parametrize("action", ["run", "move", "queue", "undo"])
@pytest.mark.parametrize("text, item", [
    (HEX + "ff", HEX_ITEM), (HEX + "x", HEX_ITEM), ("x" + HEX, HEX_ITEM), ("9" + HEX, HEX_ITEM),
    ("charlie2", CHARLIE), ("charlies", CHARLIE), ("xcharlie", CHARLIE),
    ("RFC-90111", HEX_ITEM), ("RFC 90110", HEX_ITEM), ("RFC-19011", HEX_ITEM),
])
def test_ids_and_rfc_numbers_never_match_as_substrings(action, text, item):
    words = f"undo moving {text}" if action == "undo" else text
    assert gate_says(words, action, item) != ""


@pytest.mark.parametrize("action", ["run", "move", "queue", "undo"])
@pytest.mark.parametrize("text, item", [
    (HEX, HEX_ITEM), (f"({HEX})", HEX_ITEM), (f"{HEX}.", HEX_ITEM), (f"[{HEX}],", HEX_ITEM), (f"id={HEX}!", HEX_ITEM),
    ("charlie", CHARLIE), ("charlie, please", CHARLIE), ("(charlie)", CHARLIE), ("charlie?", CHARLIE),
    ("RFC-9011", HEX_ITEM), ("RFC-09011.", HEX_ITEM),
])
def test_exact_ids_and_rfc_numbers_with_punctuation_are_allowed(action, text, item):
    words = f"undo moving {text}" if action == "undo" else text
    assert gate_says(words, action, item) == ""


@pytest.mark.asyncio
async def test_run_with_the_full_id_plus_extra_characters_is_refused(sched, monkeypatch):
    calls = charlie_queued(sched, monkeypatch)
    owner_says(monkeypatch, "start charlie2 now")
    assert not (await run()).success and calls == []
    owner_says(monkeypatch, "start (charlie) now")
    assert (await run()).success and calls == [{"expected": "charlie"}]


# --- Final review 2 at 7b35d39e (G1–G3) and CoS's fail-closed ruling for configure ---------------
# Any negation or retraction word anywhere in the owner's own words refuses every setting change.

G1_REFUSED = [
    "don't enable the scheduler", "dont enable the scheduler", "don’t enable the scheduler", "do not enable the scheduler",
    "never enable the scheduler", "no need to enable the scheduler", "I wouldn't enable the scheduler",
    "I would not enable the scheduler", "please don't ever turn on the scheduler",
    "Don't, under any circumstances, enable the scheduler", "Never, ever enable the scheduler",
    "Do not, for now, enable the scheduler", "enable the scheduler? no, don't", "enable the scheduler. Actually no, don't.",
    "enable the scheduler and don't enable the scheduler", "enable the scheduler, then disable the scheduler",
    "I'd rather you didn't enable the scheduler", "hold off: don't enable the scheduler yet",
    "enable the scheduler — just kidding, don't",
    # Under the fail-closed ruling these are refused too (they were the reviewer's "plain" cases).
    "enable the scheduler, don't wait", "never mind, enable the scheduler", "I don't want it off, enable the scheduler",
    "no, enable the scheduler", "enable the scheduler, don't disable the scheduler",
    # Every word on CoS's list, alone next to a plain request.
    "nope, enable the scheduler", "enable the scheduler jk", "cancel that, enable the scheduler",
    "stop, enable the scheduler", "nevermind, enable the scheduler", "scratch that, enable the scheduler",
    "forget it, enable the scheduler", "wait, enable the scheduler", "enable the scheduler, or undo it",
    "enable the scheduler instead", "ENABLE THE SCHEDULER, NOT!", "enable the scheduler (isn’t it off?)",
    "you can't keep it off, enable the scheduler", "enable the scheduler, it shouldn't stay off",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", G1_REFUSED)
async def test_any_negation_or_retraction_refuses_enable(sched, monkeypatch, text):
    owner_says(monkeypatch, text)
    r = await configure({"enabled": True})
    assert not r.success and sched.state()["config"]["enabled"] is False, text
    if text != "enable the scheduler, then disable the scheduler":  # no retraction word: refused as both directions
        assert "plain request" in r.error and "Self-development page" in r.error


@pytest.mark.asyncio
@pytest.mark.parametrize("text, ok", [("enable the scheduler", True), ("please turn on the scheduler", True),
                                      # H1 (review at cdf1c1d2): a quoted negation now refuses too.
                                      ("> don't enable the scheduler\nenable the scheduler", False),
                                      ('he said "don\'t enable the scheduler" but enable the scheduler', False)])
async def test_plain_enable_is_allowed_and_quoted_negations_refuse(sched, monkeypatch, text, ok):
    owner_says(monkeypatch, text)
    r = await configure({"enabled": True})
    assert r.success is ok, (text, r.error)


@pytest.mark.asyncio
@pytest.mark.parametrize("text, config", [
    ("don't set the interval to 15 minutes", {"interval_minutes": 15}),
    ("never change the interval to 15 minutes", {"interval_minutes": 15}),
    ("don't use qwen3-coder:30b for the coder", {"coder_model": "qwen3-coder:30b"}),
    ("do not switch the coder model to qwen3-coder:30b", {"coder_model": "qwen3-coder:30b"}),
    ("set the interval to 15 minutes? no, don't", {"interval_minutes": 15}),
    ("use qwen2.5vl:7b as the vision model instead", {"vision_model": "qwen2.5vl:7b"}),
    ("actually, set the vision model to qwen2.5vl:7b", {"vision_model": "qwen2.5vl:7b"}),
    ("please disable the scheduler, not now though", {"enabled": False}),
])
async def test_negation_refuses_every_chat_setting(sched, monkeypatch, text, config):
    # G2: the same fail-closed check applies to all four chat settings.
    if config.get("enabled") is False:
        state = sched.state(); state["config"]["enabled"] = True; sched.save(state)
    before = dict(sched.state()["config"])
    owner_says(monkeypatch, text)
    r = await configure(config)
    assert not r.success and sched.state()["config"] == before, text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["set the interval to 15m", "set the interval to 15 min", "set the interval to 15 mins",
                                  "set the interval to 15 minutes", "every 15 min", "make the interval 15"])
async def test_interval_unit_forms_are_accepted(sched, monkeypatch, text):
    # G3: the unit forms _INTERVAL_VALUE accepts are counted as the message's one number.
    owner_says(monkeypatch, text)
    r = await configure({"interval_minutes": 15})
    assert r.success, (text, r.error)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["set the interval to 15m, back in 5m", "set the interval to 15 min, I'll check in 2 hours"])
async def test_unit_suffixed_second_number_is_still_ambiguous(sched, monkeypatch, text):
    owner_says(monkeypatch, text)
    assert not (await configure({"interval_minutes": 15})).success


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["set the interval to 15 hours", "set the interval to 15h", "make the interval 15 days",
                                  "every 15 hours"])
async def test_interval_in_other_units_is_not_read_as_minutes(sched, monkeypatch, text):
    owner_says(monkeypatch, text)
    assert not (await configure({"interval_minutes": 15})).success


# =================================================================================================
# Final review 3 at cdf1c1d2 (H1–H5) and CoS's structural ruling: consent comes from the owner's tap
# on ANZU's existing ApprovalGrant card, bound to the exact change; wording only pre-filters refusals.
# =================================================================================================

from app.policy import approval_grant as grants  # noqa: E402

TASK = "t"


@pytest.fixture(autouse=True)
def isolated_grants(tmp_path, monkeypatch):
    monkeypatch.setattr(grants, "data_dir", lambda: tmp_path / "grants")
    (tmp_path / "grants").mkdir(exist_ok=True)


def tap(action, decision="allow_once", **arguments):
    """Mint a grant the way the owner's tap does: park the exact change, then decide from the UI.

    On code without the approval gate (cdf1c1d2) there is no change to bind, so this returns a
    dummy id; the behaviour assertions in the tests then show the bug.
    """
    pending_change = getattr(tool_module, "pending_change", None)
    if pending_change is None:
        return "no-approval-gate"
    args = {"action": action, **arguments}
    change = pending_change(args)
    assert change is not None, args
    target = tool_module.approval_target(change)
    action_id = grants.action_id_for("self_development", action, target, task_id=TASK)
    parked = grants.park_approval_request(action_id=action_id, tool_name="self_development", action=action,
                                          scope={}, target=target, task_id=TASK)
    outcome = grants.decide_approval_request(parked["id"], decision=decision, origin_channel="ui", actor="owner")
    return (outcome.get("grant") or {}).get("id") or ""


async def act(action, grant_id=None, **arguments):
    return await tool_module.SelfDevelopmentTool().execute(action, _task_id=TASK, _grant_id=grant_id, **arguments)


# --- The reviewer's 34 failing probes (test_probe670_final3.py), refused even with a tap ----------

H1_HIDDEN = [
    'Do "not" enable the scheduler', '"Don\'t" enable the scheduler', 'do `not` enable the scheduler',
    'enable the scheduler \u201cno, don\u2019t\u201d', '\u201cDon\u2019t\u201d enable the scheduler',
    "enable the scheduler \u2018til 5 \u2014 actually don\u2019t",
    "enable the scheduler 'til 5. no wait, the kids' laptop needs the GPU",
    "enable the scheduler\n> no wait, don't",
    'enable the scheduler "now \u2014 no, cancel that"', "enable the scheduler ```\nno, don't```",
]
H2_APOSTROPHES = ["don\u00b4t enable the scheduler", "don`t enable the scheduler", "don\u2032t enable the scheduler",
                  "do n't enable the scheduler"]
H3_WORDS = ["enable the scheduler. nah", "enable the scheduler \u2014 nvm", "enable the scheduler, hold on, let me check",
            "enable the scheduler. on second thought, leave it", "enable the scheduler... ignore that",
            "enable the scheduler. disregard", "enable the scheduler. hang on", "enable the scheduler. belay that"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", H1_HIDDEN + H2_APOSTROPHES + H3_WORDS)
async def test_h1_h3_negation_or_retraction_refuses_even_with_a_tap(sched, monkeypatch, text):
    owner_says(monkeypatch, text)
    grant = tap("configure", config={"enabled": True})
    r = await act("configure", grant, config={"enabled": True})
    assert not r.success and sched.state()["config"]["enabled"] is False, text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["set the interval to 15 weeks", "set the interval to 15 wk", "set the interval to 15 months",
                                  "set the interval to 15 ms", "set the interval to 15 milliseconds", "set the interval to 15 uur"])
async def test_h4_only_minute_units_are_minutes(sched, monkeypatch, text):
    owner_says(monkeypatch, text)
    grant = tap("configure", config={"interval_minutes": 15})
    r = await act("configure", grant, config={"interval_minutes": 15})
    assert not r.success and sched.state()["config"]["interval_minutes"] == 60, text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["don't start RFC-9021", "never run RFC-9021", "start RFC-9021? no, wait"])
async def test_h5_negated_run_is_refused_even_with_a_tap(sched, monkeypatch, text):
    calls = charlie_queued(sched, monkeypatch)
    owner_says(monkeypatch, text)
    grant = tap("run", item_id="charlie")
    r = await act("run", grant, item_id="charlie")
    assert not r.success and calls == [], text


@pytest.mark.parametrize("text, action", [("don't move RFC-9011 to the top", "move"), ("don't queue RFC-9011", "queue"),
                                          ("don't remove RFC-9011", "unqueue")])
def test_h5_negated_move_queue_unqueue_are_refused(text, action):
    item = {"id": "b9e2d47c1a0f3e29bb11cd13", "title": "RFC-9011 Self-development scheduler", "rfc": "9011"}
    assert tool_module.owner_asked(text, action, item=item) != ""


# --- H4 allowlist: minute units (incl. Dutch) are accepted with a tap -----------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["set the interval to 15m", "set the interval to 15 min", "set the interval to 15mins",
                                  "set the interval to 15 minute", "set the interval to 15 minutes", "set the interval to 15",
                                  "set the interval to 15 minuten", "set the interval to 15 minuut", "every 15 minuten"])
async def test_h4_minute_units_are_accepted_with_a_tap(sched, monkeypatch, text):
    owner_says(monkeypatch, text)
    grant = tap("configure", config={"interval_minutes": 15})
    r = await act("configure", grant, config={"interval_minutes": 15})
    assert r.success, (text, r.error)


# --- Approval gate --------------------------------------------------------------------------------

def six_actions(sched, monkeypatch):
    """(action, arguments, owner words, check-unchanged) for each chat-initiated state change."""
    calls = charlie_queued(sched, monkeypatch)
    async def select(item_id, revision, queued):
        calls.append({"select": (item_id, queued)})
        return {}
    monkeypatch.setattr(sched, "select", select)
    history = sched.state()["queue_history"][-1]["id"]
    revision = sched.state()["queue_revision"]
    return calls, [
        ("configure", {"config": {"enabled": True}}, "enable the self-development scheduler"),
        ("run", {"item_id": "charlie"}, "start RFC-9021"),
        ("move", {"item_id": "alpha", "position": 0, "actor": "owner", "expected_revision": revision}, "move RFC-9001 to the top"),
        ("queue", {"item_id": "alpha", "revision": "ralpha"}, "queue RFC-9001"),
        ("unqueue", {"item_id": "charlie", "revision": "rcharlie"}, "remove RFC-9021 from the queue"),
        ("undo", {"history_id": history, "actor": "owner", "expected_revision": revision}, "undo moving RFC-9021 to the top"),
    ]


def snapshot(sched, calls):
    st = sched.state()
    return (st["config"], st["order"], st["pins"], len(st["queue_history"]), len(calls))


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(6), ids=["configure", "run", "move", "queue", "unqueue", "undo"])
async def test_each_action_does_nothing_without_a_tap(sched, monkeypatch, index):
    calls, actions = six_actions(sched, monkeypatch)
    action, arguments, words = actions[index]
    owner_says(monkeypatch, words)
    before = snapshot(sched, calls)
    r = await act(action, None, **arguments)
    assert not r.success and "approval" in r.error.lower(), r.error
    assert snapshot(sched, calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(6), ids=["configure", "run", "move", "queue", "unqueue", "undo"])
async def test_a_tap_acts_exactly_once_for_the_shown_change(sched, monkeypatch, index):
    calls, actions = six_actions(sched, monkeypatch)
    action, arguments, words = actions[index]
    owner_says(monkeypatch, words)
    grant = tap(action, **arguments)
    before = snapshot(sched, calls)
    first = await act(action, grant, **arguments)
    assert first.success, first.error
    after = snapshot(sched, calls)
    assert after != before
    # Replaying the same tap does nothing.
    again = await act(action, grant, **arguments)
    assert not again.success and snapshot(sched, calls) == after


@pytest.mark.asyncio
async def test_deny_does_nothing(sched, monkeypatch):
    owner_says(monkeypatch, "enable the self-development scheduler")
    grant = tap("configure", decision="deny", config={"enabled": True})
    r = await act("configure", grant or "denied", config={"enabled": True})
    assert not r.success and sched.state()["config"]["enabled"] is False


@pytest.mark.asyncio
async def test_timeout_does_nothing(sched, monkeypatch):
    owner_says(monkeypatch, "enable the self-development scheduler")
    grant = tap("configure", config={"enabled": True})
    if grant != "no-approval-gate":
        store = grants._load(grants._store_path())
        store["items"][grant]["expires_at"] = "2000-01-01T00:00:00+00:00"
        grants._save(grants._store_path(), store)
    r = await act("configure", grant, config={"enabled": True})
    assert not r.success and sched.state()["config"]["enabled"] is False


@pytest.mark.asyncio
async def test_a_pending_request_that_timed_out_cannot_be_approved(sched, monkeypatch):
    if not hasattr(tool_module, "pending_change"):
        owner_says(monkeypatch, "enable the self-development scheduler")
        r = await act("configure", None, config={"enabled": True})
        assert not r.success  # cdf1c1d2 acts without any request: this fails there
        return
    change = tool_module.pending_change({"action": "configure", "config": {"enabled": True}})
    target = tool_module.approval_target(change)
    parked = grants.park_approval_request(action_id=grants.action_id_for("self_development", "configure", target, task_id=TASK),
                                          tool_name="self_development", action="configure", scope={}, target=target, task_id=TASK)
    grants.reject_timeout_pending(parked["id"])
    with pytest.raises(TimeoutError):
        grants.decide_approval_request(parked["id"], decision="allow_once", origin_channel="ui", actor="owner")


@pytest.mark.asyncio
async def test_a_tap_for_one_change_cannot_apply_another(sched, monkeypatch):
    owner_says(monkeypatch, "set the interval to 15 minutes")
    grant = tap("configure", config={"interval_minutes": 15})
    owner_says(monkeypatch, "set the interval to 5 minutes")
    r = await act("configure", grant, config={"interval_minutes": 5})
    assert not r.success and sched.state()["config"]["interval_minutes"] == 60
    # A run approved for charlie cannot start alpha, and a configure tap cannot start a run.
    calls = charlie_queued(sched, monkeypatch)
    owner_says(monkeypatch, "start RFC-9001")
    run_grant = tap("run", item_id="charlie")
    assert not (await act("run", run_grant, item_id="alpha")).success
    assert not (await act("run", grant, item_id="charlie")).success
    assert calls == []


@pytest.mark.asyncio
async def test_a_tap_is_bound_to_the_state_it_showed(sched, monkeypatch):
    # The card showed "interval 60 -> 15"; if the setting moved meanwhile, the tap no longer applies.
    owner_says(monkeypatch, "set the interval to 15 minutes")
    grant = tap("configure", config={"interval_minutes": 15})
    state = sched.state(); state["config"]["interval_minutes"] = 30; sched.save(state)
    r = await act("configure", grant, config={"interval_minutes": 15})
    assert not r.success and sched.state()["config"]["interval_minutes"] == 30


@pytest.mark.asyncio
async def test_an_always_tap_is_still_single_use(sched, monkeypatch):
    owner_says(monkeypatch, "enable the self-development scheduler")
    grant = tap("configure", decision="always", config={"enabled": True})
    assert (await act("configure", grant, config={"enabled": True})).success
    state = sched.state(); state["config"]["enabled"] = False; sched.save(state)
    assert not (await act("configure", grant, config={"enabled": True})).success
    assert sched.state()["config"]["enabled"] is False


@pytest.mark.asyncio
async def test_a_tap_from_another_task_does_not_apply(sched, monkeypatch):
    owner_says(monkeypatch, "enable the self-development scheduler")
    grant = tap("configure", config={"enabled": True})
    r = await tool_module.SelfDevelopmentTool().execute("configure", config={"enabled": True}, _task_id="other", _grant_id=grant)
    assert not r.success and sched.state()["config"]["enabled"] is False


def test_the_gate_parks_an_approval_card_showing_the_exact_change(sched, monkeypatch):
    from app.policy.computer_permissions import confirmation_payload_for_tool
    from app.policy.reversibility_gate import evaluate_side_effect
    monkeypatch.setattr("app.agent.coding_workers.add_decision_inbox_item", lambda **_: None, raising=False)
    args = {"action": "configure", "config": {"interval_minutes": 15}}
    decision = evaluate_side_effect("self_development", arguments=args, task_id=TASK)
    assert not decision.allowed and decision.requires_approval and decision.pending_approval_id
    payload = confirmation_payload_for_tool(call_id="c", name="self_development", arguments=args)
    assert "interval" in payload["detail"] and "60" in payload["detail"] and "15" in payload["detail"]
    charlie_queued(sched, monkeypatch)
    payload = confirmation_payload_for_tool(call_id="c", name="self_development", arguments={"action": "run", "item_id": "charlie"})
    assert "charlie" in payload["detail"] and "RFC-9021 charlie ticket" in payload["detail"]
    # Reads never park a card.
    assert evaluate_side_effect("self_development", arguments={"action": "status"}, task_id=TASK).allowed


@pytest.mark.asyncio
async def test_the_page_buttons_are_unaffected(sched, monkeypatch):
    from app.api import self_dev as page
    monkeypatch.setattr(page, "DEVELOPMENT", sched)
    cfg = ds.DevelopmentConfig.model_validate({**sched.state()["config"], "interval_minutes": 15})
    await page.scheduler_config(cfg)
    assert sched.state()["config"]["interval_minutes"] == 15
    calls = charlie_queued(sched, monkeypatch)
    await page.scheduler_run()
    assert calls == [{}]  # the page's Run calls launch() with no binding and no grant


# --- The owner's tap reaches the tool through the real agent path ---------------------------------

@pytest.mark.asyncio
async def test_registry_hands_the_tap_to_the_tool(sched, monkeypatch):
    from app.tools.registry import REGISTRY
    owner_says(monkeypatch, "enable the scheduler")
    args = {"action": "configure", "config": {"enabled": True}}
    grant = tap("configure", config={"enabled": True})
    monkeypatch.setitem(REGISTRY._context, "approval_grant_id", grant)
    r = await REGISTRY.execute("self_development", args, task_id=TASK)
    assert r.success, r.error
    assert sched.state()["config"]["enabled"] is True


@pytest.mark.asyncio
async def test_the_loop_leaves_the_tap_for_the_tool_to_check_and_spend(jarvis_env, sched, monkeypatch):
    from unittest.mock import AsyncMock
    from app.agent.loop import AGENT
    from app.policy.authorize import AuthorizationResult
    from app.policy.levels import AutonomyLevel
    from app.tools.base import ToolResult

    monkeypatch.setattr("app.agent.loop.gate_tool_call", lambda *a, **k: AuthorizationResult(
        True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "self_development.configure"))
    args = {"action": "configure", "config": {"enabled": True}}
    grant = tap("configure", config={"enabled": True})
    change = tool_module.pending_change(args)
    target = tool_module.approval_target(change)
    action_id = grants.action_id_for("self_development", "configure", target, task_id=TASK)
    seen = []

    async def execute(name, arguments, **_):
        seen.append(grants.validate_grant_for_action(grant, action_id=action_id, tool_name="self_development", target=target))
        return ToolResult(True, "ok")
    monkeypatch.setattr("app.agent.loop.REGISTRY.execute", AsyncMock(side_effect=execute))
    await AGENT._execute_tool_ex(TASK, "self_development", args, "autonomous", jarvis_env["settings"],
                                 approved=True, grant_id=grant)
    assert seen and seen[0] is not None  # the loop did not spend the tap before the tool could check it


@pytest.mark.asyncio
async def test_acting_spends_the_rfc0031_grant_itself(sched, monkeypatch):
    owner_says(monkeypatch, "enable the scheduler")
    args = {"config": {"enabled": True}}
    grant = tap("configure", **args)
    assert (await act("configure", grant, **args)).success
    change = {"action": "configure", "set": {"enabled": [False, True]}}
    target = tool_module.approval_target(change)
    action_id = grants.action_id_for("self_development", "configure", target, task_id=TASK)
    # Spent in the RFC-0031 store too, not only in the scheduler's used list.
    assert grants.validate_grant_for_action(grant, action_id=action_id, tool_name="self_development", target=target) is None


@pytest.mark.asyncio
async def test_a_run_tap_is_bound_to_the_task_revision_it_showed(sched, monkeypatch):
    calls = charlie_queued(sched, monkeypatch)
    owner_says(monkeypatch, "start RFC-9021")
    grant = tap("run", item_id="charlie")
    state = sched.state()
    state["items"]["charlie"]["revision"] = "rcharlie-edited"  # the RFC changed after the card was shown
    sched.save(state)
    r = await act("run", grant, item_id="charlie")
    assert not r.success and calls == []


# The reviewer's 14 "still allowed" probes (test_probe670_final3.py) need the owner's tap now; with it they act.
@pytest.mark.asyncio
@pytest.mark.parametrize("text, config", [(t, {"enabled": True}) for t in [
    "enable the scheduler", "please turn on the self-dev scheduler", "Enable the scheduler.",
    "it's late, enable the scheduler", "enable the scheduler for RFC-0211's work", 'enable the "self-dev" scheduler']] + [
    (t, {"interval_minutes": 15}) for t in [
    "set the interval to 15m", "set the interval to 15 min", "set the interval to 15 mins", "set the interval to 15 minutes",
    "set the interval to 15", "every 15 minutes", "set the interval to 15min", "every 15m"]])
async def test_reviewer_allowed_probes_act_with_the_tap_and_not_without(sched, monkeypatch, text, config):
    owner_says(monkeypatch, text)
    assert not (await tool_module.SelfDevelopmentTool().execute("configure", config=config, _task_id=TASK)).success
    r = await configure(config)
    assert r.success, (text, r.error)
