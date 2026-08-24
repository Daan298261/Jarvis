from app.agent.workflows import (
    builtin_workflows,
    compose_prompt,
    delete_workflow,
    get_workflow,
    list_workflows,
    merge_parameter_values,
    render_template,
    save_workflow,
)


def test_builtins_cover_requested_templates():
    ids = {item.id for item in builtin_workflows()}
    assert {"debug-project", "research-spreadsheet", "organize-files", "browser-extract", "maintenance-job"} <= ids
    debug = get_workflow("debug-project")
    assert debug is not None
    assert debug.builtin
    assert debug.execution_mode == "reliable"
    assert any("{{path}}" in step.prompt for step in debug.steps)


def test_render_and_compose_substitute_parameters():
    workflow = get_workflow("organize-files")
    assert workflow is not None
    values = merge_parameter_values(workflow, {"path": r"C:\Temp\Inbox"})
    assert values["scheme"]
    prompt = compose_prompt(workflow, values)
    assert r"C:\Temp\Inbox" in prompt
    assert "{{path}}" not in prompt
    assert "Stage 1" in prompt
    assert "Stage 4" in prompt
    assert render_template("use {{path}}", {"path": "here"}) == "use here"


def test_save_and_delete_custom_workflow(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.agent.workflows.workflows_dir", lambda: jarvis_env["tmp"] / "workflows")
    saved = save_workflow(
        {
            "id": "my-cleanup",
            "name": "My cleanup",
            "description": "Custom preset",
            "category": "filesystem",
            "execution_mode": "fast",
            "parameters": [{"key": "path", "label": "Path", "default": "D:\\tmp"}],
            "steps": [{"title": "List", "prompt": "List {{path}}"}],
        }
    )
    assert saved.builtin is False
    loaded = get_workflow("my-cleanup")
    assert loaded is not None
    assert loaded.name == "My cleanup"
    ids = {item.id for item in list_workflows()}
    assert "my-cleanup" in ids
    assert delete_workflow("my-cleanup") is True
    assert get_workflow("my-cleanup") is None


def test_cannot_delete_builtin(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.agent.workflows.workflows_dir", lambda: jarvis_env["tmp"] / "workflows")
    try:
        delete_workflow("debug-project")
        assert False, "expected PermissionError"
    except PermissionError:
        pass


async def test_run_workflow_creates_task(jarvis_env, monkeypatch):
    from app.agent.loop import AGENT
    from app.api.workflows import WorkflowRun, run_workflow
    from app.db.models import Task
    from app.db.session import SessionLocal
    from app.providers.base import ChatResult

    monkeypatch.setattr("app.agent.workflows.workflows_dir", lambda: jarvis_env["tmp"] / "workflows")

    class FakeProvider:
        async def health(self):
            return True

        async def chat(self, *args, **kwargs):
            return ChatResult(content="Done")

    jarvis_env["manager"].provider = FakeProvider()
    result = await run_workflow(
        WorkflowRun(id="debug-project", parameters={"path": str(jarvis_env["tmp"]), "command": "pytest"})
    )
    task_id = result["task"]["id"]
    assert "pytest" in result["prompt"]
    assert str(jarvis_env["tmp"]) in result["prompt"]
    if task_id in AGENT._tasks:
        await AGENT._tasks[task_id]
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
    assert task is not None
    assert task.execution_mode == "reliable"
    assert "Debug a project" in task.prompt
