"""Frontend application of replace_previous_text, run under Node 22."""

from __future__ import annotations

from tests.presence_node import run_presence_node_suite


def test_owner_chat_live_replace_suite():
    run_presence_node_suite("owner-chat-turns.test.mjs", timeout=120)
