"""BlackGrid Multimedia Studio + HR Endless Sampler integration."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.studio import blackgrid_runtime
from app.studio.workflow import build_hr_endless_api_prompt, load_ui_workflow, patch_hr_endless_prompt
from app.tools.blackgrid_studio import BlackGridStudioTool


def test_studio_capabilities_not_available_without_install():
    caps = blackgrid_runtime.studio_capabilities()
    assert caps["provider"] == "blackgrid"
    assert caps["available"] is False
    assert "hr_endless_sampler" in caps.get("operations", {})


def test_workflow_prompt_patch_and_convert():
    wf = load_ui_workflow()
    patched = patch_hr_endless_prompt(wf, "test production prompt", chunk_frames=39)
    prompt = build_hr_endless_api_prompt("hello world", chunk_frames=39, template=patched)
    assert prompt
    assert any(
        node.get("class_type") == "HREndlessSampler" or node.get("class_type") == "PrimitiveStringMultiline"
        for node in prompt.values()
    )


@pytest.mark.asyncio
async def test_blackgrid_tool_open_workbench():
    tool = BlackGridStudioTool()
    with patch.object(blackgrid_runtime, "status", AsyncMock(return_value={"portal_workbench_url": "/studio/blackgrid"})):
        result = await tool.execute(action="open_workbench")
    assert result.success
    assert result.data.get("open_in_new_tab") is True
    assert result.data.get("workbench_url") == "/studio/blackgrid"


def test_setup_interview_lists_hr_endless_in_studio_manifest():
    from app.setup_interview import STUDIO_MANIFEST

    assert "hr_endless_sampler" in STUDIO_MANIFEST
    assert STUDIO_MANIFEST["hr_endless_sampler"]["label"].startswith("HR Endless")


def test_normalize_multimedia_intent():
    from app.setup_interview import _normalize_use

    assert "multimedia" in _normalize_use("video and creative blackgrid")
