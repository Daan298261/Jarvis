"""ComfyUI UI workflow → API prompt conversion and HR Endless template patching."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

WORKFLOW_DIR = Path(__file__).resolve().parent / "workflows"
HR_ENDLESS_TEMPLATE = WORKFLOW_DIR / "hr_endless_template.json"

# PrimitiveStringMultiline "Input Text (Prompt)" in the bundled HR Endless template.
PROMPT_NODE_ID = 138
HRENDLESS_SAMPLER_NODE_ID = 141


def template_path() -> Path:
    return HR_ENDLESS_TEMPLATE


def load_ui_workflow(path: Path | None = None) -> dict[str, Any]:
    p = path or template_path()
    return json.loads(p.read_text(encoding="utf-8"))


def _widget_input_names(node: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for inp in node.get("inputs") or []:
        if inp.get("widget") is not None and inp.get("name"):
            names.append(str(inp["name"]))
    return names


def ui_workflow_to_prompt(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Best-effort conversion of ComfyUI frontend workflow JSON to /prompt body."""
    nodes = list(workflow.get("nodes") or [])
    links = list(workflow.get("links") or [])

    link_by_id: dict[int, list[Any]] = {}
    for link in links:
        if isinstance(link, list) and link:
            link_by_id[int(link[0])] = link

    outputs_by_node_slot: dict[tuple[int, int], tuple[str, int]] = {}
    for link in links:
        if not isinstance(link, list) or len(link) < 6:
            continue
        _lid, from_id, from_slot, _to_id, _to_slot, _typ = link[:6]
        outputs_by_node_slot[(int(from_id), int(from_slot))] = (str(from_id), int(from_slot))

    prompt: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if node.get("mode") == 4:
            continue
        nid = str(node["id"])
        class_type = str(node.get("type") or "")
        if not class_type or class_type in {"MarkdownNote"}:
            continue
        inputs: dict[str, Any] = {}
        widget_names = _widget_input_names(node)
        widgets_values = list(node.get("widgets_values") or [])
        w_idx = 0
        for inp in node.get("inputs") or []:
            name = inp.get("name")
            if not name:
                continue
            link_id = inp.get("link")
            if link_id is not None:
                link = link_by_id.get(int(link_id))
                if link and len(link) >= 5:
                    from_id, from_slot = int(link[1]), int(link[2])
                    inputs[str(name)] = [str(from_id), from_slot]
                continue
            if inp.get("widget") is not None and w_idx < len(widgets_values):
                inputs[str(name)] = widgets_values[w_idx]
                w_idx += 1
        while w_idx < len(widgets_values) and w_idx < len(widget_names):
            inputs[widget_names[w_idx]] = widgets_values[w_idx]
            w_idx += 1
        prompt[nid] = {"class_type": class_type, "inputs": inputs}
    return prompt


def patch_hr_endless_prompt(workflow: dict[str, Any], prompt_text: str, *, chunk_frames: int | None = None) -> dict[str, Any]:
    wf = copy.deepcopy(workflow)
    for node in wf.get("nodes") or []:
        if int(node.get("id") or 0) == PROMPT_NODE_ID:
            node["widgets_values"] = [prompt_text]
            if node.get("widgets_values_named") is not None:
                node["widgets_values_named"]["value"] = prompt_text
        if chunk_frames is not None and int(node.get("id") or 0) == HRENDLESS_SAMPLER_NODE_ID:
            wv = list(node.get("widgets_values") or [])
            if len(wv) >= 3:
                wv[2] = int(chunk_frames)
                node["widgets_values"] = wv
    return wf


def build_hr_endless_api_prompt(
    prompt_text: str,
    *,
    chunk_frames: int | None = None,
    template: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    wf = patch_hr_endless_prompt(template or load_ui_workflow(), prompt_text, chunk_frames=chunk_frames)
    return ui_workflow_to_prompt(wf)
