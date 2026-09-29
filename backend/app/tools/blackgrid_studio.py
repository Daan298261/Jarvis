"""BlackGrid Multimedia Studio — primary creative tool (HR Endless Sampler / ComfyUI)."""

from __future__ import annotations

import json
from typing import Any

from ..studio import blackgrid_runtime
from .base import RiskLevel, Tool, ToolResult


def _ok(payload: dict[str, Any], summary: str = "") -> ToolResult:
    return ToolResult(True, summary or json.dumps(payload, default=str)[:4000], data=payload)


class BlackGridStudioTool(Tool):
    name = "blackgrid_studio"
    description = (
        "Open or drive BlackGrid Multimedia Studio (local ComfyUI + HR Endless Sampler). "
        "Use open_workbench for the Jarvis input/output page (opens in a new browser tab). "
        "Use open_comfy for the ComfyUI graph. Use submit_hr_endless to queue long-form MiniMax H3 video "
        "from a text prompt. Install/start when the sidecar is missing."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open_workbench",
                    "open_comfy",
                    "status",
                    "install",
                    "start",
                    "submit_hr_endless",
                    "list_outputs",
                ],
            },
            "prompt": {"type": "string", "description": "Full HR Endless / MiniMax H3 production prompt"},
            "chunk_frames": {"type": "integer", "description": "Frames per H3 chunk (VRAM tradeoff)", "default": 39},
            "reference_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional absolute paths to reference images on disk",
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        if action == "open_workbench":
            snap = await blackgrid_runtime.status()
            payload = {
                "workbench_url": snap.get("portal_workbench_url") or "/studio/blackgrid",
                "open_in_new_tab": True,
                "detail": "Open the Jarvis BlackGrid workbench for prompt input and rendered outputs.",
            }
            return _ok(payload, "Open BlackGrid workbench in a new browser tab.")
        if action == "open_comfy":
            snap = await blackgrid_runtime.status()
            if not snap.get("running"):
                started = await blackgrid_runtime.start()
                if not started.get("ok"):
                    return ToolResult(False, "", error=started.get("detail") or "ComfyUI is not running.")
            payload = {
                "comfy_ui_url": snap.get("comfy_ui_url") or blackgrid_runtime._base_url(),
                "open_in_new_tab": True,
                "template": "Jarvis-HR-Endless-Sampler.json",
            }
            return _ok(payload, "Open ComfyUI in a new browser tab.")
        if action == "status":
            snap = await blackgrid_runtime.status()
            caps = await blackgrid_runtime.studio_capabilities_async()
            return _ok({"module": snap, "capabilities": caps}, "BlackGrid studio status.")
        if action == "install":
            result = await blackgrid_runtime.install_and_enable()
            ok = result.get("ok") or result.get("install_status") == "ready"
            if not ok:
                return ToolResult(False, "", error=result.get("detail") or "Install failed", data=result)
            return _ok(result, "BlackGrid install finished.")
        if action == "start":
            result = await blackgrid_runtime.start()
            if not result.get("ok"):
                return ToolResult(False, "", error=result.get("detail") or "Start failed", data=result)
            return _ok(result, "ComfyUI started.")
        if action == "submit_hr_endless":
            prompt = str(kwargs.get("prompt") or "").strip()
            if not prompt:
                return ToolResult(False, "", error="prompt is required for submit_hr_endless")
            chunk = int(kwargs.get("chunk_frames") or 39)
            refs = [str(x) for x in (kwargs.get("reference_images") or []) if str(x).strip()]
            try:
                job = await blackgrid_runtime.submit_hr_endless_job(prompt, chunk_frames=chunk, reference_images=refs)
            except Exception as exc:
                return ToolResult(False, "", error=str(exc))
            payload = {
                **job,
                "workbench_url": "/studio/blackgrid",
                "open_in_new_tab": True,
                "detail": "Job queued in ComfyUI. Monitor progress in the workbench or ComfyUI HR Endless Preview node.",
            }
            return _ok(payload, "HR Endless job queued.")
        if action == "list_outputs":
            outputs = await blackgrid_runtime.list_outputs()
            return _ok({"outputs": outputs, "workbench_url": "/studio/blackgrid"}, f"{len(outputs)} output file(s).")
        return ToolResult(False, "", error=f"Unknown action: {action}")
