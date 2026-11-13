"""RFC-0211 Away Mode, shared upcoming queue, independent review, gated merge and build.

The end-to-end tests drive the real scheduler, real git worktrees, a real bare
``origin`` repository and real merges. Only the external edges are replaced: the
Ollama worker process (writes a change and a result), the model reviewer verdict,
GitHub's PR/CI API (emulated on the bare repository) and the Windows packager.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.agent import development_build as builds
from app.agent import development_publish as publish
from app.agent import development_queue as q
from app.agent import development_review as review
from app.agent import development_scheduler as ds
from app.tools import self_development as tool_module


# ----------------------------------------------------------------------------- queue


def make_state(*items):
    state = ds.default_state()
    for index, item in enumerate(items):
        item.setdefault("status", "available")
        item.setdefault("revision", f"rev-{item['id']}")
        item.setdefault("created_at", index)
        item.setdefault("acceptance", True)
        item.setdefault("kind", "rfc")
        item.setdefault("title", item["id"])
        state["items"][item["id"]] = item
    q.replan(state)
    return state


def test_planning_orders_by_priority_then_oldest_and_keeps_owner_pins():
    state = make_state({"id": "a", "priority": 3}, {"id": "b", "priority": 1}, {"id": "c", "priority": 3})
    assert state["order"] == ["b", "a", "c"]
    q.move(state, "c", to=0, expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    assert state["order"][0] == "c" and "c" in state["pins"]
    state["items"]["d"] = {"id": "d", "priority": 0, "status": "available", "created_at": 9, "acceptance": True, "kind": "rfc", "title": "d", "revision": "r"}
    q.replan(state)
    # Automatic planning never silently undoes the owner's order.
    assert state["order"][0] == "c"
    assert state["order"][1] == "d"


def test_anzu_reorder_needs_reason_and_cannot_move_owner_pins():
    state = make_state({"id": "a"}, {"id": "b"}, {"id": "c"})
    q.move(state, "c", to=0, expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    with pytest.raises(ValueError, match="reason"):
        q.move(state, "b", to=0, expected_revision=state["queue_revision"], actor=q.ANZU, reason="")
    with pytest.raises(ValueError, match="pinned"):
        q.move(state, "b", to=0, expected_revision=state["queue_revision"], actor=q.ANZU, reason="deadline")
    result = q.move(state, "b", to=1, expected_revision=state["queue_revision"], actor=q.ANZU, reason="dependency ready")
    assert result["changed"] and state["order"] == ["c", "b", "a"]
    assert state["queue_history"][-1]["actor"] == "anzu" and state["queue_history"][-1]["before"] == ["c", "a", "b"]


def test_stale_reorder_and_set_changes_are_rejected():
    state = make_state({"id": "a"}, {"id": "b"})
    stale = state["queue_revision"]
    q.move(state, "b", to=0, expected_revision=stale, actor=q.OWNER, reason="")
    with pytest.raises(q.StaleQueue):
        q.move(state, "a", to=0, expected_revision=stale, actor=q.OWNER, reason="")
    with pytest.raises(ValueError, match="exactly"):
        q.reorder(state, ["a", "a"], expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    with pytest.raises(ValueError, match="exactly"):
        q.reorder(state, ["a"], expected_revision=state["queue_revision"], actor=q.OWNER, reason="")


def test_undo_restores_previous_order_and_anzu_cannot_undo_the_owner():
    state = make_state({"id": "a"}, {"id": "b"}, {"id": "c"})
    q.move(state, "c", to=0, expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    entry = state["queue_history"][-1]["id"]
    with pytest.raises(ValueError, match="cannot undo"):
        q.undo(state, entry, expected_revision=state["queue_revision"], actor=q.ANZU)
    q.undo(state, entry, expected_revision=state["queue_revision"], actor=q.OWNER)
    assert state["order"] == ["a", "b", "c"] and "c" not in state["pins"]
    q.move(state, "b", to=0, expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    q.release_pin(state, "b", expected_revision=state["queue_revision"])
    assert state["order"] == ["a", "b", "c"]


def test_reordering_cannot_bypass_dependencies_evidence_or_acceptance():
    state = make_state(
        {"id": "base", "rfc": "0901", "priority": 3},
        {"id": "dependent", "rfc": "0902", "priority": 3, "depends": ["RFC-0901"]},
        {"id": "vague", "rfc": "0903", "acceptance": False},
        {"id": "claimed", "rfc": "0904"},
        {"id": "done", "rfc": "0905"},
        {"id": "unmapped", "kind": "drive", "maps_to": ""},
    )
    state["evidence"] = {"merged": {"0905": 12}, "open": {"0904": 13}, "checked_at": 1, "error": ""}
    q.move(state, "dependent", to=0, expected_revision=state["queue_revision"], actor=q.OWNER, reason="")
    chosen, reasons = q.next_eligible(state, automatic=True)
    explained = {r["id"]: r["reason"] for r in reasons}
    assert chosen["id"] == "base"
    assert explained["dependent"] == "Waiting for RFC-0901"
    assert "acceptance" in explained["vague"]
    assert "Claimed by open PR #13" == explained["claimed"]
    assert "Delivered by PR #12" == explained["done"]
    assert "does not map" in explained["unmapped"]
    state["items"]["base"]["status"] = "delivered"
    q.replan(state)
    assert q.next_eligible(state, automatic=True)[0]["id"] == "dependent"


def test_failed_revision_is_not_retried_automatically():
    state = make_state({"id": "a"})
    state["items"]["a"].update(status="needs_attention", attempted_revision="rev-a")
    q.replan(state)
    assert q.next_eligible(state, automatic=True)[0] is None
    state["items"]["a"]["revision"] = "rev-a2"
    assert q.next_eligible(state, automatic=True)[0]["id"] == "a"


def test_ticket_metadata_and_master_plan_intake():
    meta = q.ticket_metadata("RFC-0950 thing", "**Priority:** P1\n**Depends on:** RFC-0050 and RFC-0060\n\n## Acceptance\n- works", path="docs/rfcs/0950-thing.md")
    assert meta == {"priority": 1, "depends": ["RFC-0050", "RFC-0060"], "rfc": "0950", "acceptance": True}
    assert q.ticket_metadata("x", "no criteria")["acceptance"] is False
    plan = "## 58. DEVELOPMENT QUEUE\n\n### P1\n\n- [ ] Fix it\n  - Acceptance: it works.\n  - Status: TODO\n\n- [x] Done thing\n  - Acceptance: yes\n\n### P2\n\n- [ ] Blocked thing\n  - Acceptance: later\n  - Status: BLOCKED (no GPU)\n\n## 59. NEXT\n- [ ] not in queue\n"
    entries = q.plan_items(plan)
    assert [(e["title"], e["priority"], e["plan_status"]) for e in entries] == [("Fix it", 1, "TODO"), ("Blocked thing", 2, "BLOCKED")]
    real = q.plan_items((Path(__file__).resolve().parents[1] / "JARVIS_MASTER_PLAN.md").read_text(encoding="utf-8"))
    assert real and all(entry["title"] for entry in real)


# ----------------------------------------------------------------------------- review


def test_policy_findings_reject_stubs_removed_tests_specs_and_masked_ci():
    diff = """diff --git a/backend/x.py b/backend/x.py
+++ b/backend/x.py
+def feature():
+    raise NotImplementedError
diff --git a/tests/test_x.py b/tests/test_x.py
+++ b/tests/test_x.py
-def test_keeps_working():
+@pytest.mark.skip
diff --git a/.github/workflows/pr-tests.yml b/.github/workflows/pr-tests.yml
+++ b/.github/workflows/pr-tests.yml
+        continue-on-error: true
"""
    findings = review.policy_findings(["backend/x.py", "tests/test_x.py", "docs/rfcs/0001-x.md", ".github/workflows/pr-tests.yml"], diff)
    issues = " | ".join(f["issue"] for f in findings)
    assert "Stub" in issues and "removed without replacement" in issues and "skipped" in issues
    assert "Architect-owned" in issues and "continue-on-error" in issues and "CI workflow" in issues
    assert all(f["severity"] == "blocker" for f in findings)
    assert review.policy_findings(["backend/x.py"], "diff --git a/backend/x.py b/backend/x.py\n+++ b/backend/x.py\n+value = 1\n") == []


@pytest.mark.asyncio
async def test_model_review_requires_a_strict_verdict(monkeypatch):
    seen = {}

    def answer(content):
        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": content}})
        return handler

    real = httpx.AsyncClient

    def client(content):
        return lambda **kw: real(transport=httpx.MockTransport(answer(content)), **kw)

    monkeypatch.setattr(review.httpx, "AsyncClient", client(json.dumps({"approved": True, "findings": [], "north_star": "Polished"})))
    verdict = await review.model_review(ollama_url="http://127.0.0.1:11434", model="m", prompt="p", keep_alive="300s")
    assert verdict["approved"] and seen["keep_alive"] == "300s" and seen["format"] == "json"
    monkeypatch.setattr(review.httpx, "AsyncClient", client("I think it is fine"))
    with pytest.raises(review.ReviewError, match="unreadable"):
        await review.model_review(ollama_url="http://127.0.0.1:11434", model="m", prompt="p", keep_alive="300s")
    monkeypatch.setattr(review.httpx, "AsyncClient", client(json.dumps({"approved": "yes"})))
    with pytest.raises(review.ReviewError, match="schema"):
        await review.model_review(ollama_url="http://127.0.0.1:11434", model="m", prompt="p", keep_alive="300s")


# ----------------------------------------------------------------------------- away intent


@pytest.mark.parametrize("text,expected", [
    ("Hey, I'm AFK, go develop yourself", "activate"),
    ("turn on away mode please", "activate"),
    ("I'm back", "deactivate"),
    ("stop developing", "deactivate"),
    ("The doc says \"I'm AFK, go develop yourself\" — what does that do?", ""),
    ("> I'm AFK, go develop yourself\nsummarise this quote", ""),
    ("I'll be AFK tomorrow", ""),
    # Phone keyboards send typographic apostrophes (review blocker 6).
    ("I\u2019m back", "deactivate"),
    ("Hey, I\u2019m AFK, go develop yourself", "activate"),
    ("I\u2018m back", "deactivate"),
    ("Im back", "deactivate"),
    ("I\u2019ll be AFK tomorrow", ""),
    ("The doc says \u201cI\u2019m back\u201d \u2014 what does that do?", ""),
])
def test_away_intent_only_counts_the_owners_own_words(text, expected):
    assert tool_module.away_intent(text) == expected


@pytest.mark.asyncio
async def test_chat_tool_changes_away_mode_only_on_a_direct_owner_request(monkeypatch):
    calls = []

    async def set_away(enabled, **kwargs):
        calls.append(enabled)
        return {"away": {"enabled": enabled}}

    monkeypatch.setattr(ds.DEVELOPMENT, "set_away", set_away)
    monkeypatch.delenv("ANZU_DEVELOPMENT_MISSION", raising=False)
    tool = tool_module.SelfDevelopmentTool()
    async def quoted(_task): return "Summarise this RFC: 'I'm AFK, go develop yourself' activates Away Mode"
    monkeypatch.setattr(tool_module, "latest_owner_message", quoted)
    refused = await tool.execute("away_on", _task_id="task")
    assert not refused.success and calls == []
    assert not (await tool.execute("away_on")).success
    async def direct(_task): return "Hey, I'm AFK, go develop yourself"
    monkeypatch.setattr(tool_module, "latest_owner_message", direct)
    assert (await tool.execute("away_on", _task_id="task")).success and calls == [True]


# ----------------------------------------------------------------------------- end to end


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


RFC_ALPHA = "# RFC-0901 Alpha\n\n**Status:** accepted\n**Priority:** P1\n\n## Acceptance\n- alpha.txt says alpha\n"
RFC_BETA = "# RFC-0902 Beta\n\n**Status:** accepted\n**Priority:** P0\n**Depends on:** RFC-0901\n\n## Acceptance\n- beta.txt says beta\n"


class FakeGitHub:
    """PRs and CI emulated on the real bare origin; merges are real git merges."""

    def __init__(self, origin: Path, scratch: Path):
        self.origin = origin
        self.scratch = scratch
        self.prs: dict[int, dict] = {}
        self.merges: list[int] = []
        self.ci = "passed"

    def ensure_pr(self, repo, *, branch, base, title, body):
        for number, pr in self.prs.items():
            if pr["branch"] == branch:
                return number
        number = len(self.prs) + 1
        self.prs[number] = {"branch": branch, "base": base, "title": title, "body": body, "state": "OPEN"}
        return number

    def head(self, number):
        return git(self.origin, "rev-parse", f"refs/heads/{self.prs[number]['branch']}")

    def check_outcome(self, repo, number, head_sha):
        if self.head(number) != head_sha:
            return {"outcome": "head_changed", "detail": "PR head moved"}
        return {"outcome": self.ci, "detail": f"CI {self.ci}", "checks": []}

    def merge_pr(self, repo, number, head_sha):
        assert self.head(number) == head_sha
        pr = self.prs[number]
        if pr["state"] != "MERGED":
            work = self.scratch / f"merge-{number}"
            subprocess.run(["git", "clone", "-q", "-b", pr["base"], str(self.origin), str(work)], check=True)
            git(work, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "--no-ff", "-m", f"Merge PR #{number}", f"origin/{pr['branch']}")
            git(work, "push", "-q", "origin", pr["base"])
            pr.update(state="MERGED", merge_sha=git(work, "rev-parse", "HEAD"))
            self.merges.append(number)
        return pr["merge_sha"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    owner = tmp_path / "owner"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "development", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "development", str(seed)], check=True)
    for name, text in {"AGENTS.md": "agents", "docs/PROCESS.md": "process", "ANZU_PRODUCT_NORTH_STAR.md": "Polished, trustworthy.",
                       "docs/rfcs/0901-alpha.md": RFC_ALPHA, "docs/rfcs/0902-beta.md": RFC_BETA}.items():
        (seed / name).parent.mkdir(parents=True, exist_ok=True)
        (seed / name).write_text(text, encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "development")
    subprocess.run(["git", "clone", "-q", "-b", "development", str(origin), str(owner)], check=True)

    control = tmp_path / "scheduler"
    control.mkdir()
    monkeypatch.setattr(ds, "root", lambda: control)
    monkeypatch.setattr(ds, "kill_switch_active", lambda: False)
    monkeypatch.setattr("app.agent.worktrees.worktrees_root", lambda: (tmp_path / "worktrees").resolve())
    monkeypatch.setattr("app.agent.proactivity.autonomy_root", lambda: tmp_path)
    monkeypatch.setattr("app.engine_mode.model_enabled", lambda *a: True)
    monkeypatch.setattr(ds, "models_held_unloaded", lambda: False)
    async def capabilities(config): return {}
    monkeypatch.setattr(ds, "model_capabilities", capabilities)
    monkeypatch.setattr(publish, "pr_evidence", lambda repo: {"slug": "o/r", "merged": {}, "open": {}})
    hub = FakeGitHub(origin, tmp_path)
    monkeypatch.setattr(publish, "ensure_pr", hub.ensure_pr)
    monkeypatch.setattr(publish, "check_outcome", hub.check_outcome)
    monkeypatch.setattr(publish, "merge_pr", hub.merge_pr)

    verdicts = []
    async def model_review(**kwargs):
        verdicts.append(kwargs["prompt"])
        return world.verdicts.pop(0) if world.verdicts else {"approved": True, "findings": [], "north_star": "Meets the North Star"}
    monkeypatch.setattr(review, "model_review", model_review)
    tests_seen = []
    def verification(path, control_dir, timeout, base_sha):
        tests_seen.append(git(path, "rev-parse", "HEAD"))
        ok = world.verification_ok.pop(0) if world.verification_ok else True
        return {"ok": ok, "checks": [{"command": ["python", "-m", "pytest"], "returncode": 0 if ok else 1, "output": "1 passed" if ok else "1 failed"}]}
    monkeypatch.setattr("app.agent.development_worker.verification", verification)

    missions = []
    def popen(command, **kwargs):
        control_dir = Path(command[-1])
        mission = json.loads((control_dir / "mission.json").read_text(encoding="utf-8"))
        missions.append(mission)
        target = Path(mission["spec"]["path"])
        name = mission["item"]["title"].split()[-1].lower()
        text = f"{name}\n" + ("repaired\n" if mission["findings"] else "")
        (target / f"{name}.txt").write_text(text, encoding="utf-8")
        ds.write_json(control_dir / "result.json", {"status": "review_ready", "verification": {"ok": True}})
        return SimpleNamespace(pid=os.getpid(), poll=lambda: 0)
    monkeypatch.setattr(ds, "spawn_worker", popen)

    built = []
    def start(repo, job):
        built.append(job["merge_sha"])
        return {**job, "status": "running", "attempts": job["attempts"] + 1}
    def poll(job):
        if job["status"] != "running":
            return job
        artifact = tmp_path / f"{job['merge_sha']}.exe"
        artifact.write_bytes(b"MZ" + b"0" * 10)
        return {**job, "status": "succeeded", "artifact": str(artifact), "sha256": "f" * 64}
    monkeypatch.setattr(builds, "start", start)
    monkeypatch.setattr(builds, "poll", poll)

    scheduler = ds.DevelopmentScheduler()
    state = scheduler.state()
    state["config"]["repo"] = str(owner)
    scheduler.save(state)
    world = SimpleNamespace(scheduler=scheduler, hub=hub, owner=owner, origin=origin, missions=missions, verdicts=[],
                            verification_ok=[], tests_seen=tests_seen, reviews=verdicts, built=built, tmp=tmp_path)
    yield world
    scheduler.release()


async def run_until(world, predicate, limit=60):
    for _ in range(limit):
        await world.scheduler.tick()
        state = world.scheduler.state()
        if predicate(state):
            return state
    raise AssertionError(f"condition not reached; deliveries={json.dumps(list(world.scheduler.state()['deliveries'].values()), default=str)[:3000]}")


def delivered(title):
    return lambda state: any(d["title"].endswith(title) and d["stage"] == "delivered" for d in state["deliveries"].values())


@pytest.mark.asyncio
async def test_away_mode_end_to_end_two_tasks_with_review_repair(world):
    world.verdicts = [{"approved": False, "findings": [{"severity": "blocker", "file": "alpha.txt", "issue": "say repaired"}], "north_star": ""}]
    result = await world.scheduler.set_away(True, actor="owner")
    assert result["explanation"] == ds.AWAY_EXPLANATION
    state = await run_until(world, delivered("Alpha"))
    alpha = next(d for d in state["deliveries"].values() if d["title"].endswith("Alpha"))
    # Dependencies: Beta has the higher priority but waits for Alpha; Alpha went first.
    assert world.missions[0]["item"]["title"].endswith("Alpha")
    # Rejected review → repair mission in the same worktree → re-test → approval bound to the new head.
    assert alpha["repairs"] == 1 and world.missions[1]["findings"].startswith("Independent review findings")
    assert alpha["review"]["approved"] and alpha["review"]["head_sha"] == alpha["tests"]["head_sha"]
    assert "repaired" in git(world.origin, "show", f"{alpha['merge_sha']}:alpha.txt")
    assert state["builds"][alpha["merge_sha"]]["status"] == "succeeded"
    state = await run_until(world, delivered("Beta"))
    beta = next(d for d in state["deliveries"].values() if d["title"].endswith("Beta"))
    # Beta was built on top of the merged Alpha (development moved during the run → merged and re-validated).
    assert git(world.origin, "show", "development:alpha.txt").startswith("alpha")
    assert git(world.origin, "show", "development:beta.txt") == "beta"
    assert world.hub.merges == [1, 2] and world.built == [alpha["merge_sha"], beta["merge_sha"]]
    # Nothing else is eligible; a further tick does not re-implement a delivered ticket.
    await world.scheduler.tick()
    assert len(world.missions) == 3
    back = await world.scheduler.set_away(False, actor="owner")
    summary = back["away"]["summary"]
    assert [c["title"] for c in summary["completed"]] == ["RFC-0901 Alpha", "RFC-0902 Beta"]
    assert summary["merged_prs"] == [1, 2] and all(c["artifact"] for c in summary["completed"])


@pytest.mark.asyncio
async def test_failing_verification_is_never_published_even_if_ci_would_pass(world):
    world.verification_ok = [False, False, False]
    await world.scheduler.set_away(True, actor="owner")
    state = await run_until(world, lambda s: any(d["stage"] == "needs_attention" for d in s["deliveries"].values()))
    delivery = next(iter(state["deliveries"].values()))
    assert delivery["repairs"] == 2 and "Repair limit" in delivery["error"]
    assert world.hub.prs == {} and world.hub.merges == []
    assert world.reviews == []  # review never ran on a failing head


@pytest.mark.asyncio
async def test_changed_pr_head_blocks_merge(world, monkeypatch):
    await world.scheduler.set_away(True, actor="owner")
    state = await run_until(world, lambda s: any(d["stage"] == "waiting_ci" for d in s["deliveries"].values()))
    delivery = next(iter(state["deliveries"].values()))
    # Someone pushes another commit to the PR branch after approval.
    other = world.tmp / "intruder"
    subprocess.run(["git", "clone", "-q", "-b", delivery["branch"], str(world.origin), str(other)], check=True)
    (other / "alpha.txt").write_text("tampered\n", encoding="utf-8")
    git(other, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qam", "tamper")
    git(other, "push", "-q", "origin", delivery["branch"])
    state = await run_until(world, lambda s: next(iter(s["deliveries"].values()))["stage"] == "needs_attention")
    assert "did not review" in next(iter(state["deliveries"].values()))["error"]
    assert world.hub.merges == []


@pytest.mark.asyncio
async def test_concurrent_base_change_revalidates_before_merge(world):
    await world.scheduler.set_away(True, actor="owner")
    state = await run_until(world, lambda s: any(d["stage"] == "waiting_ci" for d in s["deliveries"].values()))
    first = next(iter(state["deliveries"].values()))
    reviewed_head = first["review"]["head_sha"]
    other = world.tmp / "colleague"
    subprocess.run(["git", "clone", "-q", "-b", "development", str(world.origin), str(other)], check=True)
    (other / "colleague.txt").write_text("x\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qm", "colleague")
    git(other, "push", "-q", "origin", "development")
    tests_before = len(world.tests_seen)
    state = await run_until(world, delivered("Alpha"))
    alpha = next(iter(state["deliveries"].values()))
    assert alpha["base_changes"] == 1 and alpha["review"]["head_sha"] != reviewed_head
    assert len(world.tests_seen) > tests_before and world.tests_seen[-1] == alpha["review"]["head_sha"]
    assert git(world.origin, "show", f"{alpha['merge_sha']}:colleague.txt") == "x"


@pytest.mark.asyncio
async def test_build_failure_is_recoverable_without_a_second_merge_and_survives_restart(world, monkeypatch):
    def unavailable(repo, job):
        raise builds.BuildUnavailable("Development builds need the Windows packaging host")
    real_start = builds.start
    monkeypatch.setattr(builds, "start", unavailable)
    await world.scheduler.set_away(True, actor="owner")
    state = await run_until(world, lambda s: any(d["stage"] == "build_failed" for d in s["deliveries"].values()))
    alpha = next(iter(state["deliveries"].values()))
    assert state["items"][alpha["item_id"]]["status"] == "build_failed"
    assert q.waiting_reason(state, state["items"][alpha["item_id"]], automatic=True).startswith("Merged")
    # Beta depends on Alpha's delivery outcome, so it is not dispatched.
    beta = next(i for i in state["items"].values() if i["title"].endswith("Beta"))
    assert q.waiting_reason(state, beta, automatic=True) == "Waiting for RFC-0901"
    monkeypatch.setattr(builds, "start", real_start)
    restarted = ds.DevelopmentScheduler()  # a restart reads the persisted ledger
    world.scheduler = restarted
    monkeypatch.setattr(builds, "start", lambda repo, job: {**job, "status": "running", "attempts": job["attempts"] + 1})
    await restarted.retry_build(alpha["merge_sha"])
    state = await run_until(world, delivered("Alpha"))
    assert world.hub.merges == [1]
    assert state["builds"][alpha["merge_sha"]]["attempts"] == 2


@pytest.mark.asyncio
async def test_returning_stops_new_work_and_checkpoints_the_running_mission(world, monkeypatch):
    finished = []

    def slow_popen(command, **kwargs):
        control_dir = Path(command[-1])
        mission = json.loads((control_dir / "mission.json").read_text(encoding="utf-8"))
        (Path(mission["spec"]["path"]) / "partial.txt").write_text("half done\n", encoding="utf-8")
        finished.append(mission)
        return SimpleNamespace(pid=os.getpid(), poll=lambda: None)

    monkeypatch.setattr(ds, "spawn_worker", slow_popen)
    monkeypatch.setattr(world.scheduler, "owned_process", lambda run: SimpleNamespace())
    monkeypatch.setattr(world.scheduler, "stop_process", lambda run: None)
    await world.scheduler.set_away(True, actor="owner")
    await run_until(world, lambda s: any(r["status"] == "running" for r in s["runs"]))
    back = await world.scheduler.set_away(False, actor="owner", reason="I'm back")
    delivery = back["deliveries"][0]
    assert delivery["stage"] == "stopped" and delivery["checkpoint_sha"]
    assert git(delivery["worktree"], "show", f"{delivery['checkpoint_sha']}:partial.txt") == "half done"
    assert back["status"]["phase"] == "paused"
    for _ in range(3):
        await world.scheduler.tick()
    assert len(finished) == 1 and world.hub.prs == {}
    from app.agent.proactivity import get_away_mode
    assert get_away_mode().enabled is False


@pytest.mark.asyncio
async def test_resource_reservation_and_manual_unload_hold_dispatch(world, monkeypatch):
    state = world.scheduler.state()
    state["config"]["resource_hold"] = "Grokbot reverse-engineering"
    world.scheduler.save(state)
    await world.scheduler.set_away(True, actor="owner")
    await world.scheduler.tick()
    public = world.scheduler.public()
    assert public["status"]["phase"] == "waiting for priority work" and world.missions == []
    state = world.scheduler.state()
    state["config"]["resource_hold"] = ""
    world.scheduler.save(state)
    monkeypatch.setattr(ds, "models_held_unloaded", lambda: True)
    await world.scheduler.tick()
    assert world.missions == [] and "unloaded" in world.scheduler.public()["status"]["detail"]


# ----------------------------------------------------------------------------- GitHub + build adapters


class FakeGh:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        for prefix, (code, out, err) in self.responses:
            if args[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(args, code, out, err)
        raise AssertionError(f"unexpected gh call {args}")


def test_pr_evidence_marks_merged_and_claimed_rfcs(monkeypatch):
    monkeypatch.setattr(publish, "github_slug", lambda repo: "o/r")
    rows = [{"number": 5, "title": "RFC-0901 alpha", "state": "MERGED", "headRefName": "a"},
            {"number": 6, "title": "RFC-0902: beta", "state": "OPEN", "headRefName": "b"},
            {"number": 7, "title": "RFC-0903 mine", "state": "OPEN", "headRefName": "jarvis/self-dev-abc"},
            {"number": 8, "title": "docs only", "state": "MERGED", "headRefName": "c"}]
    monkeypatch.setattr(publish, "gh", FakeGh([(["pr", "list"], (0, json.dumps(rows), ""))]))
    evidence = publish.pr_evidence("repo")
    assert evidence["merged"] == {"0901": 5} and evidence["open"] == {"0902": 6}


@pytest.mark.parametrize("required,checks,outcome", [
    ((1, "", "no required checks reported"), [{"name": "pytest", "bucket": "pass", "state": "SUCCESS"}], "passed"),
    ((0, json.dumps([{"name": "pytest", "bucket": "fail", "state": "FAILURE"}]), ""), None, "failed"),
    ((0, json.dumps([{"name": "pytest", "bucket": "pending", "state": "IN_PROGRESS"}]), ""), None, "pending"),
])
def test_check_outcome_reads_exact_head_checks(monkeypatch, required, checks, outcome):
    monkeypatch.setattr(publish, "github_slug", lambda repo: "o/r")
    monkeypatch.setattr(publish, "pr_state", lambda repo, n: {"state": "OPEN", "head": "h" * 40, "merge_sha": "", "base": "development"})
    calls = []
    def gh(args, **kwargs):
        calls.append(args)
        if "--required" in args:
            return subprocess.CompletedProcess(args, *required[:2], required[2])
        return subprocess.CompletedProcess(args, 0, json.dumps(checks), "")
    monkeypatch.setattr(publish, "gh", gh)
    assert publish.check_outcome("repo", 3, "h" * 40)["outcome"] == outcome
    assert publish.check_outcome("repo", 3, "x" * 40)["outcome"] == "head_changed"


def test_merge_pr_refuses_a_changed_head_and_pins_the_reviewed_commit(monkeypatch):
    monkeypatch.setattr(publish, "github_slug", lambda repo: "o/r")
    states = iter([{"state": "OPEN", "head": "h" * 40, "merge_sha": ""}, {"state": "MERGED", "head": "h" * 40, "merge_sha": "m" * 40}])
    monkeypatch.setattr(publish, "pr_state", lambda repo, n: next(states))
    calls = []
    monkeypatch.setattr(publish, "gh_ok", lambda args, **kw: calls.append(args) or "")
    assert publish.merge_pr("repo", 4, "h" * 40) == "m" * 40
    assert calls == [["pr", "merge", "4", "--repo", "o/r", "--merge", "--match-head-commit", "h" * 40]]
    monkeypatch.setattr(publish, "pr_state", lambda repo, n: {"state": "OPEN", "head": "z" * 40, "merge_sha": ""})
    with pytest.raises(publish.PublishError, match="head changed"):
        publish.merge_pr("repo", 4, "h" * 40)


def test_build_requires_windows_and_only_a_real_artifact_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(builds, "builds_root", lambda: tmp_path)
    if os.name != "nt":
        with pytest.raises(builds.BuildUnavailable, match="Windows"):
            builds.start("repo", builds.new_job("a" * 40, "item", 1))
    checkout = tmp_path / "checkout"
    (checkout / builds.ARTIFACT).parent.mkdir(parents=True)
    exit_file = tmp_path / "build-1.exit"
    job = {**builds.new_job("a" * 40, "item", 1), "status": "running", "pid": os.getpid(), "created": 0, "checkout": str(checkout),
           "exit_file": str(exit_file), "log": str(tmp_path / "build-1.log"), "attempts": 1}
    assert builds.poll(job)["status"] == "failed"  # interrupted: no exit status recorded
    exit_file.write_text("0\n", encoding="utf-8")
    assert "without a usable" in builds.poll(job)["error"]  # success claimed, no installer
    (checkout / builds.ARTIFACT).write_bytes(b"MZ" + b"\0" * builds.MIN_ARTIFACT_BYTES)
    done = builds.poll(job)
    assert done["status"] == "succeeded" and len(done["sha256"]) == 64
    assert (tmp_path / ("a" * 40) / "SHA256SUMS").read_text(encoding="utf-8").startswith(done["sha256"])
