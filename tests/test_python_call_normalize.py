from app.tools.call_normalize import extract_python_copy_pair, normalize_tool_call, salvage_action_blob
from app.tools.python_exec import PythonTool, normalize_python_call


def test_salvage_qwen_run_code_gt_blob():
    raw = {
        "action": 'run_code>\nimport os, subprocess\n\nrepo = r"C:\\Users\\daanv\\Documents\\jarvis-test"\nprint(os.path.exists(repo))'
    }
    out = normalize_python_call(raw)
    assert out["action"] == "run_code"
    assert "import os" in out["code"]
    assert "jarvis-test" in out["code"]


def test_command_field_becomes_code():
    out = normalize_python_call({"action": "run_code", "command": "print(1)"})
    assert out["code"] == "print(1)"


def test_bare_script_becomes_run_code():
    out = normalize_python_call({"action": "import os\nprint(1)"})
    assert out["action"] == "run_code"
    assert out["code"].startswith("import os")


async def test_execute_salvages_run_code_gt_blob():
    tool = PythonTool()
    result = await tool.execute(
        action='run_code>\nprint("ok-salvage")',
        timeout_seconds=30,
    )
    assert result.success
    assert "ok-salvage" in result.output


def test_filesystem_action_blob_is_salvaged():
    class Fake:
        parameters = {"properties": {"action": {"enum": ["copy", "list", "search"]}}}

    out = salvage_action_blob(
        "filesystem",
        {"action": r"copy>\nC:\src\a"},
        Fake(),
    )
    assert out["action"] == "copy"
    assert r"C:\src\a" in out["path"]


def test_python_copy_script_reroutes_to_filesystem():
    code = (
        "import shutil\n"
        r'src = r"C:\Users\daanv\Documents\projects\jarvis"' + "\n"
        r'dst = r"C:\Users\daanv\Documents\jarvis-test"' + "\n"
        "shutil.copytree(src, dst, dirs_exist_ok=True)\n"
    )
    pair = extract_python_copy_pair(code)
    assert pair == (
        r"C:\Users\daanv\Documents\projects\jarvis",
        r"C:\Users\daanv\Documents\jarvis-test",
    )
    name, args = normalize_tool_call("python", {"action": "run_code", "code": code})
    assert name == "filesystem"
    assert args["action"] == "copy"
    assert args["path"].endswith("jarvis")
    assert args["destination"].endswith("jarvis-test")
