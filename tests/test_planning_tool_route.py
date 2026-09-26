from __future__ import annotations

from app.agent.planning import requests_agent_tools, route_request, split_long_owner_prompt
from app.agent.planning import MANAGED_TASK


def test_requests_agent_tools_detects_run_tool_phrases():
    assert requests_agent_tools("Please run the filesystem tool on my vault")
    assert requests_agent_tools("use the terminal tool to list files")
    assert not requests_agent_tools("hello there")


def test_route_request_sends_tool_asks_to_managed_task():
    route = route_request("execute the git tool and show status")
    assert route.kind == MANAGED_TASK


def test_split_long_owner_prompt_chunks():
    text = ("paragraph one. " * 40 + "paragraph two. " * 40).strip()
    chunks = split_long_owner_prompt(text, max_chars=400)
    assert len(chunks) >= 2
    assert sum(len(c) for c in chunks) >= len(text) * 0.85
