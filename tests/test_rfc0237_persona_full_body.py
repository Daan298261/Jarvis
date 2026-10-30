from tests.presence_node import run_presence_node_suite


def test_full_body_anatomy_safe_framing_and_live_mode_transitions():
    run_presence_node_suite("persona-full-body.test.mjs", timeout=120)
