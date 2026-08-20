from app.agent.planning import classify_task, parse_plan_block, resolve_execution_policy


def test_parse_plan_block_extracts_sections():
    text = """
END STATE: a folder named Jarvis-Test exists on the desktop with system-specs.txt
ACCEPTANCE CRITERIA:
- folder exists
- file is non-empty
PLAN:
1. inspect desktop
2. create folder
3. write file
"""
    parsed = parse_plan_block(text)
    assert "Jarvis-Test" in parsed["end_state"]
    assert parsed["acceptance_criteria"] == ["folder exists", "file is non-empty"]
    assert parsed["plan"][0] == "inspect desktop"


def test_classify_task_categories():
    assert classify_task("Organize these files on the desktop") == "filesystem"
    assert classify_task("Fix the login bug in this repository and run pytest") == "software engineering"
    assert classify_task("Open the website and save the page title") == "browser automation"


def test_execution_policies():
    assert resolve_execution_policy("fast").max_verify_tools == 1
    assert resolve_execution_policy("reliable").critic_pass is True
    assert resolve_execution_policy("reliable").require_verify_tools is True
    assert resolve_execution_policy("nope").name == "balanced"
