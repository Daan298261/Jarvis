from app.tools.terminal import TerminalTool, _python_args, default_shell


def test_python_shell_uses_dash_c_for_snippets():
    args = _python_args("import time; time.sleep(1)")
    assert args[1:] == ["-c", "import time; time.sleep(1)"]
    assert args[0]
    print_args = _python_args("print('hi')")
    assert print_args[1:] == ["-c", "print('hi')"]
    file_args = _python_args("script.py --flag")
    assert file_args[1:3] == ["script.py", "--flag"]


async def test_background_process_can_be_inspected_and_killed(tmp_path):
    tool = TerminalTool()
    started = await tool.execute(
        action="start",
        shell="python",
        command="import time; time.sleep(20)",
        working_directory=str(tmp_path),
    )
    assert started.success, started.error
    pid = started.data["pid"]
    assert pid

    inspected = await tool.execute(action="inspect", pid=pid)
    assert inspected.success
    assert inspected.data["alive"] is True
    assert inspected.data["pid"] == pid

    listed = await tool.execute(action="inspect")
    assert any(job["pid"] == pid for job in listed.data.get("jobs") or [])

    killed = await tool.execute(action="kill", pid=pid)
    assert killed.success
    inspected_after = await tool.execute(action="inspect", pid=pid)
    assert inspected_after.data["alive"] is False


async def test_wait_collects_output_from_a_started_process(tmp_path):
    tool = TerminalTool()
    started = await tool.execute(
        action="start",
        shell="python",
        command="print('hello-from-bg')",
        working_directory=str(tmp_path),
    )
    assert started.success, started.error
    waited = await tool.execute(action="wait", pid=started.data["pid"], timeout_seconds=10)
    assert waited.success
    assert waited.data["alive"] is False
    assert "hello-from-bg" in (waited.data.get("stdout") or waited.output)


def test_linux_default_shell_is_not_powershell():
    import sys

    if sys.platform == "win32":
        assert default_shell() == "powershell"
    else:
        assert default_shell() in {"bash", "python"}
