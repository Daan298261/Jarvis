import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.agent.task_workflow import (
    append_followup, is_large_request, load_workflow, prepare_workflow, workflow_payload,
)
from app.config import AppSettings
from app.db.models import Task
from app.db.session import SessionLocal
from app.providers.base import ChatResult


async def make_task(task_id="workflow-test"):
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Large task", prompt="Original exact request", status="running"))
        await session.commit()
    return task_id


def planner_for(*steps):
    return AsyncMock(return_value=ChatResult(content=json.dumps({
        "goal": "Create the artifact", "constraints": "Keep C:/owner/output.txt", "steps": list(steps),
    })))


async def prepare(task_id, planner, reviews=True):
    return await prepare_workflow(task_id, "Original exact request", brief="Original exact request",
                                  source_ref="read_ingress blob_id=source", reviews=reviews, planner=planner)


async def test_plan_is_committed_before_work_and_survives_reload(jarvis_env):
    task_id = await make_task()
    planner = planner_for("Inspect input", "Produce output")
    workflow = await prepare(task_id, planner)
    assert [s.kind for s in workflow.steps] == ["work", "work", "bugfix", "fact_check", "quality_control"]
    assert [s.ordinal for s in workflow.steps] == [1, 2, 3, 4, 5]
    assert all(s.status == "pending" for s in workflow.steps)
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        assert len(json.loads(task.plan_json)) == 5
        assert task.prompt == "Original exact request"
    again = await prepare(task_id, planner)
    assert planner.await_count == 1
    assert again.current.id == workflow.current.id
    assert planner.call_args.kwargs["tools"] is None


async def test_each_prompt_keeps_all_bounded_predecessors_not_transcripts(jarvis_env):
    task_id = await make_task()
    workflow = await prepare(task_id, planner_for("Inspect", "Build"))
    await workflow.mark_running()
    await workflow.finish_current("first artifact C:/owner/a.txt\n" + "x" * 50000)
    workflow = await load_workflow(task_id)
    assert workflow.current.ordinal == 2
    await workflow.finish_current("second artifact C:/owner/b.txt\n" + "y" * 50000)
    prompt = workflow.prompt()
    assert "first artifact" in prompt and "second artifact" in prompt
    assert "C:/owner/output.txt" in prompt
    assert len(prompt) < 6500
    assert "read_ingress blob_id=source" in prompt
    assert workflow.current.kind == "bugfix"
    stored = await workflow_payload(task_id)
    assert len(stored[0]["result"]) > 50000


async def test_reviews_are_optional_but_plan_is_not(jarvis_env):
    workflow = await prepare(await make_task(), planner_for("Make deliverable"), reviews=False)
    assert [s.kind for s in workflow.steps] == ["work"]
    assert AppSettings().large_task_reviews is True


@pytest.mark.parametrize("content", ["not JSON", '{"goal":"x","steps":[]}',
                                     '{"goal":"x","steps":[42]}'])
async def test_invalid_planner_blocks_before_execution(jarvis_env, content):
    task_id = await make_task()
    with pytest.raises(RuntimeError, match="no valid bounded plan"):
        await prepare(task_id, AsyncMock(return_value=ChatResult(content=content)))
    assert await workflow_payload(task_id) == []


async def test_failure_cannot_skip_remaining_prompts_or_complete_task(jarvis_env):
    from app.agent.loop import AgentRuntime

    task_id = await make_task()
    workflow = await prepare(task_id, planner_for("Inspect", "Build"))
    agent = AgentRuntime()
    with pytest.raises(RuntimeError, match="before all stored prompts"):
        await agent._update(task_id, status="completed", result="done")
    async with SessionLocal() as session:
        assert (await session.get(Task, task_id)).status == "running"
    # Use the same transaction semantics as the runner; failure remains resumable.
    from app.db.models import TaskPromptStep
    async with SessionLocal() as session:
        row = await session.get(TaskPromptStep, workflow.current.id)
        row.status = "failed"
        await session.commit()
    restored = await load_workflow(task_id)
    assert restored.current.ordinal == 1
    await restored.mark_running()
    assert (await workflow_payload(task_id))[0]["status"] == "running"


async def test_followup_keeps_existing_pending_work_and_deduplicates(jarvis_env):
    workflow = await prepare(await make_task(), planner_for("Inspect", "Build"))
    workflow = await append_followup(workflow, "Also create a README", reviews=True)
    assert workflow.current.ordinal == 1
    assert len(workflow.steps) == 9
    assert "Also create a README" in workflow.prompt()
    again = await append_followup(workflow, "Also create a README", reviews=True)
    assert len(again.steps) == 9
    assert [s.kind for s in again.steps][-3:] == ["bugfix", "fact_check", "quality_control"]


def test_small_chat_does_not_trigger_workflow():
    assert not is_large_request("Hello, how are you?")
    assert is_large_request("1. Inspect files\n2. Create a report\n3. Fix bugs")
    assert is_large_request("Build this", complexity=4)
    assert is_large_request("Create a website for me")
    assert is_large_request("Build a desktop app")
    assert is_large_request("Write a novel about the sea")
    assert not is_large_request("Create a folder")


async def test_status_miss_never_waits_for_hardware_or_remote_probe(monkeypatch):
    from app.inference.status_monitor import ModelStatusMonitor
    monitor = ModelStatusMonitor()
    gate = asyncio.Event()
    async def slow(_):
        await gate.wait()
        return {"healthy": True}
    monkeypatch.setattr("app.inference.manager.MANAGER.live_snapshot", slow)
    monkeypatch.setattr("app.inference.manager.MANAGER.live_state_overlay", lambda: {"loaded": True})
    monkeypatch.setattr("app.inference.manager.MANAGER.unprobed_snapshot", lambda _: pytest.fail("sync hardware probe"))
    try:
        snapshots = await asyncio.wait_for(asyncio.gather(*[
            monitor.get_snapshot(AppSettings()) for _ in range(20)
        ]), timeout=.2)
        assert all(not s["healthy"] and s["status_refresh_pending"] for s in snapshots)
        await asyncio.sleep(0)
        assert monitor.probe_count == 1
        gate.set()
        await monitor._refresh_task
        assert (await monitor.get_snapshot(AppSettings()))["healthy"] is True
    finally:
        monitor.stop()


def test_front_envelope_has_one_leading_system_message():
    from app.agent.front_responder import small_context_envelope
    from app.providers.base import ChatMessage
    messages = small_context_envelope("What is RAM?", [ChatMessage(role="user", content="Hello")],
                                      action_hint="final_basic")
    assert [m.role for m in messages].count("system") == 1
    assert messages[0].role == "system"
    assert "Hint front_action: final_basic" in messages[0].content
    assert messages[-1].content == "What is RAM?"


async def test_real_agent_runs_committed_prompts_and_reviews_with_fresh_context(jarvis_env, monkeypatch):
    import re
    from app.agent.loop import AGENT
    from app.agent.task_workflow import PLAN_SYSTEM
    from app.agent.prompts import VERIFY_PROMPT
    target = jarvis_env["tmp"] / "workflow-report.txt"
    jarvis_env["settings"].front_responder.enabled = False
    monkeypatch.setattr("app.agent.loop.record_trajectory", AsyncMock())
    monkeypatch.setattr("app.agent.loop.publish_owner_text", AsyncMock(return_value={}))
    class Provider:
        name = "scripted"
        def __init__(self): self.calls = []; self.stage_calls = {}
        async def health(self): return True
        async def chat(self, messages, tools=None, **kwargs):
            self.calls.append(list(messages))
            if any(PLAN_SYSTEM in str(m.content) for m in messages):
                assert tools is None
                return ChatResult(content=json.dumps({"goal":"Create report", "constraints":str(target),
                    "steps":["Write the requested report", "Read the report and confirm its contents"]}))
            stage = next((m.content for m in messages if m.role == "user" and "Execute ONLY prompt" in str(m.content)), "")
            match = re.search(r"Execute ONLY prompt (\d+)/", stage)
            if match:
                index = int(match[1]); self.stage_calls[index] = self.stage_calls.get(index, 0) + 1
                assert len(await workflow_payload(self.task_id)) == 5
                if tools and (self.stage_calls[index] == 1 or messages[-1].content == VERIFY_PROMPT):
                    args = {"action":"read", "path":str(target)}
                    if index == 1 and not target.exists():
                        args = {"action":"write", "path":str(target), "content":"VERIFIED REPORT", "create_backup":False}
                    return ChatResult(tool_calls=[{"id":f"phase-{index}-{self.stage_calls[index]}", "type":"function",
                        "function":{"name":"filesystem", "arguments":json.dumps(args)}}])
                return ChatResult(content=f"Stage {index} independently verified. Artifact: {target}")
            return ChatResult(content="Acknowledged")
    provider = Provider()
    jarvis_env["manager"].provider = provider
    # Persist first, then call the actual runner to avoid a test-only request path.
    task_id = await make_task("full-workflow")
    provider.task_id = task_id
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        task.prompt = f"Write an end-to-end text report to {target}. Contents: VERIFIED REPORT."
        task.task_class = "filesystem"; task.profile = "fast"; task.response_route = "managed_task"
        task.autonomy = "autonomous"
        await session.commit()
    await asyncio.wait_for(AGENT._run(task_id, continue_existing=False), 40)
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        assert task.status == "completed", task.error
    steps = await workflow_payload(task_id)
    assert [s["status"] for s in steps] == ["completed"] * 5
    assert set(provider.stage_calls) == {1, 2, 3, 4, 5}
    assert target.read_text() == "VERIFIED REPORT"
    for index in range(2, 6):
        first_call = next(ms for ms in provider.calls if any(
            f"Execute ONLY prompt {index}/" in str(m.content) for m in ms))
        assert not any(m.role == "tool" for m in first_call)
        assert "Stage 1 independently verified" in "\n".join(str(m.content) for m in first_call)


async def test_optional_model_catalog_cannot_block_status_reader(monkeypatch):
    from app.inference.model_details_cache import ModelDetailsCache
    cache = ModelDetailsCache()
    gate = asyncio.Event()
    async def slow():
        await gate.wait()
        return {"profiles":[{"name":"front_08b"}], "outcomes":{}}
    monkeypatch.setattr(cache, "collect", slow)
    try:
        for _ in range(20):
            result = cache.read()
            assert result["details_cache"]["pending"] is True
            assert not result["details_cache"]["available"]
        await asyncio.sleep(0)
        gate.set()
        await cache.task
        assert cache.read()["profiles"] == [{"name":"front_08b"}]
    finally:
        cache.stop()


async def test_review_toggle_roundtrips_through_settings_api(tmp_path, monkeypatch):
    from app import config
    from app.api.settings import update_settings, SettingsUpdate
    monkeypatch.setattr(config, "repo_root", lambda: tmp_path)
    assert config.load_settings().large_task_reviews is True
    await update_settings(SettingsUpdate(large_task_reviews=False))
    assert config.load_settings().large_task_reviews is False
    await update_settings(SettingsUpdate(large_task_reviews=True))
    assert config.load_settings().large_task_reviews is True


async def test_front_switch_is_background_and_unrelated_settings_do_not_restart(tmp_path, monkeypatch):
    from app import config
    from app.api import settings as api_settings
    monkeypatch.setattr(config, "repo_root", lambda: tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def restart(settings):
        calls.append(settings.front_responder.profile)
        entered.set()
        await release.wait()
    monkeypatch.setattr("app.inference.front_runtime.FRONT_RUNTIME.ensure_started", restart)
    try:
        await api_settings.stop_front_reconfigure()
        await asyncio.wait_for(api_settings.update_settings(
            api_settings.SettingsUpdate(front_responder_profile="front_08b")), .2)
        await entered.wait()
        assert calls == ["front_08b"]
        await api_settings.update_settings(api_settings.SettingsUpdate(large_task_reviews=False))
        assert calls == ["front_08b"]
        release.set()
        await api_settings._front_reconfigure_task
    finally:
        release.set()
        await api_settings.stop_front_reconfigure()


async def test_cancelled_front_start_releases_only_owned_backend(monkeypatch):
    from app.inference import front_runtime as front
    from app.config import AppSettings
    entered = asyncio.Event()
    class Backend:
        def __init__(self, settings): pass
        def missing_requirements(self, profile): return []
        async def start(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        async def stop(self): stopped.append(True)
    stopped = []
    monkeypatch.setattr(front, "LlamaCppBackend", Backend)
    runtime = front.FrontRuntime()
    task = asyncio.create_task(runtime._start_local(AppSettings(), front.FrontDecision(profile="front_08b")))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert stopped == [True]
    assert runtime._backend is None


async def test_removing_task_removes_its_saved_plan_and_prompt_results(jarvis_env):
    from sqlalchemy import select
    from app.db.models import TaskPromptPlan, TaskPromptStep
    task_id = await make_task()
    await prepare(task_id, planner_for("Inspect", "Build"))
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        await session.delete(task)
        await session.commit()
    async with SessionLocal() as session:
        assert await session.get(TaskPromptPlan, task_id) is None
        assert not list((await session.scalars(select(TaskPromptStep).where(TaskPromptStep.task_id == task_id))).all())


async def test_resume_keeps_current_prompt_effect_history_but_drops_completed_phase(jarvis_env):
    from app.providers.base import ChatMessage
    workflow = await prepare(await make_task(), planner_for("Inspect", "Build"))
    history = [ChatMessage(role="user", content=workflow.prompt()),
               ChatMessage(role="assistant", content="Created C:/artifact.txt"),
               ChatMessage(role="tool", content="File created", tool_call_id="write1")]
    assert workflow.owns_history(history)
    await workflow.finish_current("Artifact created")
    assert not workflow.owns_history(history)
    current = [ChatMessage(role="user", content=workflow.prompt())]
    assert workflow.owns_history(current)
    # Content from a different task cannot make an old conversation current.
    current[0].content = current[0].content.replace(workflow.task_id, "another-task")
    assert not workflow.owns_history(current)


async def test_model_can_read_exact_prior_results_only_for_its_current_task(jarvis_env):
    from app.tools.read_ingress import ReadIngressTool
    workflow = await prepare(await make_task("own-task"), planner_for("Inspect"))
    await workflow.finish_current("X" * 4500 + "EXACT ARTIFACT: C:/owner/result.txt")
    foreign = await prepare(await make_task("foreign-task"), planner_for("Inspect"))
    await foreign.finish_current("OTHER OWNER DATA")
    tool = ReadIngressTool()
    result = await tool.execute(_task_id="own-task", prompt_step=1, offset=4500, limit=9000)
    assert result.success and "EXACT ARTIFACT" in result.output
    assert "OTHER OWNER DATA" not in result.output
    assert result.data["has_more"] is False
    assert not (await tool.execute(prompt_step=1, offset=0)).success
    assert not (await tool.execute(_task_id="own-task", prompt_step=2, offset=0)).success
    assert not (await tool.execute(_task_id="missing-task", prompt_step=1, offset=0)).success


@pytest.mark.parametrize("text", ["What is RAM?", "What is the difference between RAM and storage? One sentence.", "How does a rainbow form?"])
async def test_basic_questions_finish_on_front_without_worker(text):
    from app.agent.front_responder import generate_front_reply, terminal_front_completes_turn
    class Fast:
        async def chat_stream(self, messages, **kwargs):
            yield "RAM holds temporary working data."
    result = await generate_front_reply(text, settings=AppSettings(), provider=Fast())
    assert result.action == "final_basic"
    assert terminal_front_completes_turn(result.action)
    assert not result.skipped


@pytest.mark.parametrize("text", ["What is my current RAM usage?", "What is the safest medicine dose?", "What is the latest price?", "How do I invest my pension?", "Run the filesystem tool"])
def test_live_personal_high_stakes_and_actions_keep_worker(text):
    from app.decision.owner_turn import infer_rules_reply_shape
    assert infer_rules_reply_shape(text) != "basic_qa"


async def test_missing_basic_question_provider_never_completes_with_fake_greeting():
    from app.agent.front_responder import generate_front_reply, worker_required
    result = await generate_front_reply("What is RAM?", settings=AppSettings(), provider=object())
    assert worker_required(result.action)
    assert result.text == ""
