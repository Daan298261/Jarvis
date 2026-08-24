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
    assert resolve_execution_policy("fast").best_of_n == 1
    assert resolve_execution_policy("reliable").critic_pass is True
    assert resolve_execution_policy("reliable").require_verify_tools is True
    assert resolve_execution_policy("reliable").best_of_n == 3
    assert resolve_execution_policy("nope").name == "balanced"


def test_parse_plan_candidates_extracts_labeled_strategies():
    from app.agent.planning import parse_plan_candidates, select_best_plan

    text = """
PLAN A
END STATE: file exists via library
ACCEPTANCE CRITERIA:
- file exists
PLAN:
1. inspect the folder
2. write with the filesystem tool

PLAN B
END STATE: file exists via GUI
ACCEPTANCE CRITERIA:
- file exists
PLAN:
1. screenshot the desktop
2. click Save
"""
    candidates = parse_plan_candidates(text)
    assert [c.label for c in candidates] == ["A", "B"]
    assert "inspect" in candidates[0].plan[0]
    chosen = select_best_plan(candidates, "SELECTED: B\nREASON: user asked for GUI")
    assert chosen.label == "B"
    fallback = select_best_plan(candidates, "both are fine")
    assert fallback.label == "A"
