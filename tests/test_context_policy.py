from app.agent.compaction import compact_history, estimate_prompt_tokens
from app.agent.context_policy import CONTEXT_LONG, CONTEXT_NORMAL, CONTEXT_SIMPLE, initial_context_size, next_context_size
from app.inference.manager import MANAGER
from app.inference.profiles import PROFILES, expert_profile, with_context
from app.providers.base import ChatMessage


def test_simple_tasks_start_at_8k():
    assert initial_context_size("filesystem", PROFILES["balanced"]) == CONTEXT_SIMPLE
    assert initial_context_size("shell", PROFILES["fast"]) == CONTEXT_SIMPLE
    assert initial_context_size("office", PROFILES["quality"]) == CONTEXT_SIMPLE


def test_long_tasks_start_at_16k_not_profile_cap():
    assert initial_context_size("software engineering", PROFILES["balanced"]) == CONTEXT_NORMAL
    assert initial_context_size("long-horizon autonomous", PROFILES["balanced"]) == CONTEXT_NORMAL
    assert initial_context_size("mixed", PROFILES["balanced"]) == CONTEXT_NORMAL
    assert PROFILES["balanced"].context_size == CONTEXT_NORMAL


def test_fast_profile_cannot_exceed_its_cap():
    assert initial_context_size("research", PROFILES["fast"]) == min(CONTEXT_NORMAL, PROFILES["fast"].context_size)


def test_context_grows_under_pressure_and_never_shrinks():
    assert next_context_size(8192, 32768, 1000) is None
    assert next_context_size(8192, 32768, 6000) == CONTEXT_NORMAL
    assert next_context_size(16384, 32768, 12000) == CONTEXT_LONG
    assert next_context_size(32768, 32768, 30000) is None
    compacted = next_context_size(8192, 32768, 4500, compacted=True)
    assert compacted == CONTEXT_NORMAL


def test_with_context_copies_profile():
    grown = with_context(PROFILES["fast"], 32768)
    assert grown.context_size == 32768
    assert grown.filename == PROFILES["fast"].filename
    assert PROFILES["fast"].context_size == 8192


def test_expert_profile_stays_compact():
    expert = expert_profile()
    assert expert.context_size == 16384
    assert "27B" in expert.filename


def test_token_estimate_scales_with_history():
    messages = [ChatMessage(role="user", content="x" * 400)]
    assert estimate_prompt_tokens(messages) == 100
    long_history = compact_history(
        [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="go")]
        + [ChatMessage(role="assistant", content="y" * 200) for _ in range(12)],
        keep_last=4,
    )
    assert estimate_prompt_tokens(long_history) > 0


async def test_apply_context_grows_without_backend(jarvis_env):
    MANAGER.backend = None
    MANAGER.state.context_size = 8192
    grown = await MANAGER.apply_context(jarvis_env["settings"], 16384, allow_shrink=False)
    assert grown == 16384
    shrunk = await MANAGER.apply_context(jarvis_env["settings"], 8192, allow_shrink=False)
    assert shrunk == 16384
    forced = await MANAGER.apply_context(jarvis_env["settings"], 8192, allow_shrink=True)
    assert forced == 8192


async def test_filesystem_agent_task_starts_at_8k(jarvis_env):
    from app.agent.loop import AGENT
    from app.providers.base import ChatResult
    from tests.test_verification_loop import ScriptedProvider, _finished, _tool

    tmp = jarvis_env["tmp"]
    target = tmp / "ctx.txt"
    MANAGER.backend = None
    MANAGER.state.context_size = 32768
    provider = ScriptedProvider(
        [
            ChatResult(content="END STATE: ctx.txt exists\nACCEPTANCE CRITERIA:\n- file contains CTX\nPLAN:\n1. write"),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "CTX", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Wrote it."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified ctx.txt contains CTX."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Organize files on the desktop: write {target} containing CTX.",
        autonomy="autonomous",
        profile="balanced",
        execution_mode="fast",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    assert task.task_class == "filesystem"
    assert MANAGER.state.context_size == CONTEXT_SIMPLE

