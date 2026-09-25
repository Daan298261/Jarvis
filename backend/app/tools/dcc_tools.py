"""Local DCC CLI tools (Blender, OpenSCAD, optional FreeCAD) — RFC-0120."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from ..projects.paths import project_media_dir
from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path

_BLENDER_INSTALL = (
    "Blender is not installed or not on PATH. Install Blender from https://www.blender.org/download/ "
    "and ensure `blender` is available, or add a Module Catalog pack when published (RFC-0090)."
)
_OPENSCAD_INSTALL = (
    "OpenSCAD is not installed or not on PATH. Install OpenSCAD from https://openscad.org/downloads.html "
    "and ensure `openscad` is available, or add a Module Catalog pack when published (RFC-0090)."
)
_FREECAD_INSTALL = (
    "FreeCAD is not installed or not on PATH. Install FreeCAD and ensure `freecadcmd` is available."
)


def _allowed(context: dict[str, Any]) -> list[str]:
    return list(context.get("allowed_directories") or [])


def _resolve(raw: str, allowed: list[str]) -> Path:
    return resolve_allowed_path(raw, allowed) if allowed else Path(raw).expanduser().resolve()


async def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 600) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, "", "DCC command timed out"
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    return int(proc.returncode or 0), out, err


def _place_in_project(project_id: str, output: Path) -> Path | None:
    if not project_id or not output.exists():
        return None
    dest_dir = project_media_dir(project_id)
    dest = dest_dir / output.name
    shutil.copy2(output, dest)
    return dest


class BlenderTool(Tool):
    name = "blender"
    description = (
        "Run Blender headless against owner-allowed paths. "
        "Use background_python with a .py script, or export_mesh from a .blend file. "
        "Returns the on-disk output path; missing Blender yields an install CTA, not success."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["background_python", "export_mesh"]},
            "script_path": {"type": "string", "description": "Python script for --background --python"},
            "blend_path": {"type": "string", "description": "Optional .blend to open"},
            "output_path": {"type": "string", "description": "Export path (.stl, .obj, .glb, ...)"},
            "project_id": {"type": "string", "description": "Optional portal project for RFC-0121 media placement"},
            "timeout_seconds": {"type": "integer", "default": 600},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    async def execute(self, **kwargs: Any) -> ToolResult:
        exe = shutil.which("blender")
        if not exe:
            return ToolResult(False, "", error=_BLENDER_INSTALL)
        action = str(kwargs.get("action") or "").strip()
        allowed = _allowed(self.context_getter() or {})
        timeout = int(kwargs.get("timeout_seconds") or 600)
        project_id = str(kwargs.get("project_id") or "").strip()
        if action == "background_python":
            script_raw = kwargs.get("script_path") or ""
            if not script_raw:
                return ToolResult(False, "", error="script_path is required for background_python")
            try:
                script = _resolve(script_raw, allowed)
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))
            argv = [exe, "--background"]
            blend_raw = kwargs.get("blend_path") or ""
            if blend_raw:
                try:
                    blend = _resolve(blend_raw, allowed)
                except PermissionError as exc:
                    return ToolResult(False, "", error=str(exc))
                argv.append(str(blend))
            argv.extend(["--python", str(script)])
            code, out, err = await _run(argv, timeout=timeout)
            if code != 0:
                return ToolResult(False, out or err, error=err or f"blender exited {code}")
            output_raw = kwargs.get("output_path") or ""
            output_path = ""
            if output_raw:
                try:
                    output_path = str(_resolve(output_raw, allowed))
                except PermissionError as exc:
                    return ToolResult(False, "", error=str(exc))
            placed = _place_in_project(project_id, Path(output_path)) if output_path else None
            data = {"output_path": output_path, "project_media_path": str(placed) if placed else ""}
            text = out.strip() or f"Blender script finished: {script}"
            if output_path:
                text += f"\noutput_path={output_path}"
            return ToolResult(True, text, data=data)
        if action == "export_mesh":
            blend_raw = kwargs.get("blend_path") or ""
            output_raw = kwargs.get("output_path") or ""
            if not blend_raw or not output_raw:
                return ToolResult(False, "", error="export_mesh requires blend_path and output_path")
            try:
                blend = _resolve(blend_raw, allowed)
                output = _resolve(output_raw, allowed)
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))
            output.parent.mkdir(parents=True, exist_ok=True)
            py = (
                "import bpy\n"
                f"bpy.ops.export_mesh.stl(filepath=r'{output}')\n"
            )
            # Generic export via bpy.ops.wm based on extension when STL operator unavailable.
            ext = output.suffix.lower()
            if ext == ".obj":
                py = f"import bpy\nbpy.ops.export_scene.obj(filepath=r'{output}')\n"
            elif ext == ".glb":
                py = f"import bpy\nbpy.ops.export_scene.gltf(filepath=r'{output}', export_format='GLB')\n"
            script_tmp = output.parent / f".jarvis-blender-export-{output.stem}.py"
            script_tmp.write_text(py, encoding="utf-8")
            argv = [exe, "--background", str(blend), "--python", str(script_tmp)]
            code, out, err = await _run(argv, timeout=timeout)
            try:
                script_tmp.unlink(missing_ok=True)
            except OSError:
                pass
            if code != 0 or not output.exists():
                return ToolResult(False, out or err, error=err or "Blender export did not produce output")
            placed = _place_in_project(project_id, output)
            data = {"output_path": str(output), "project_media_path": str(placed) if placed else ""}
            return ToolResult(True, f"Exported {output}", data=data)
        return ToolResult(False, "", error=f"Unknown action {action}")


class OpenScadTool(Tool):
    name = "openscad"
    description = (
        "Compile an OpenSCAD .scad file to a mesh/export on disk via `openscad -o <out> <in>`. "
        "Missing OpenSCAD returns an install CTA, not a fake mesh."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "input_path": {"type": "string", "description": ".scad source file"},
            "output_path": {"type": "string", "description": "Output mesh (.stl, .obj, .amf, ...)"},
            "project_id": {"type": "string", "description": "Optional portal project for RFC-0121 media placement"},
            "timeout_seconds": {"type": "integer", "default": 300},
        },
        "required": ["input_path", "output_path"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    async def execute(self, **kwargs: Any) -> ToolResult:
        exe = shutil.which("openscad")
        if not exe:
            return ToolResult(False, "", error=_OPENSCAD_INSTALL)
        allowed = _allowed(self.context_getter() or {})
        try:
            src = _resolve(str(kwargs.get("input_path") or ""), allowed)
            dest = _resolve(str(kwargs.get("output_path") or ""), allowed)
        except PermissionError as exc:
            return ToolResult(False, "", error=str(exc))
        if not src.exists():
            return ToolResult(False, "", error=f"Input not found: {src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        timeout = int(kwargs.get("timeout_seconds") or 300)
        argv = [exe, "-o", str(dest), str(src)]
        code, out, err = await _run(argv, timeout=timeout)
        if code != 0 or not dest.exists():
            return ToolResult(False, out or err, error=err or f"openscad exited {code}")
        project_id = str(kwargs.get("project_id") or "").strip()
        placed = _place_in_project(project_id, dest)
        data = {"output_path": str(dest), "project_media_path": str(placed) if placed else ""}
        return ToolResult(True, f"Compiled {src} -> {dest}", data=data)


class FreecadTool(Tool):
    name = "freecad"
    description = (
        "Optional documented local DCC: run FreeCADCmd with a Python macro on allowed paths. "
        "Missing freecadcmd returns an install CTA."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "macro_path": {"type": "string", "description": "Python macro executed by FreeCADCmd"},
            "output_path": {"type": "string", "description": "Expected export path"},
            "project_id": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 600},
        },
        "required": ["macro_path"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    async def execute(self, **kwargs: Any) -> ToolResult:
        exe = shutil.which("freecadcmd") or shutil.which("FreeCADCmd")
        if not exe:
            return ToolResult(False, "", error=_FREECAD_INSTALL)
        allowed = _allowed(self.context_getter() or {})
        try:
            macro = _resolve(str(kwargs.get("macro_path") or ""), allowed)
        except PermissionError as exc:
            return ToolResult(False, "", error=str(exc))
        if not macro.exists():
            return ToolResult(False, "", error=f"Macro not found: {macro}")
        timeout = int(kwargs.get("timeout_seconds") or 600)
        argv = [exe, str(macro)]
        code, out, err = await _run(argv, timeout=timeout)
        if code != 0:
            return ToolResult(False, out or err, error=err or f"freecadcmd exited {code}")
        output_raw = str(kwargs.get("output_path") or "").strip()
        output_path = ""
        if output_raw:
            try:
                output_path = str(_resolve(output_raw, allowed))
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))
        project_id = str(kwargs.get("project_id") or "").strip()
        placed = _place_in_project(project_id, Path(output_path)) if output_path else None
        data = {"output_path": output_path, "project_media_path": str(placed) if placed else ""}
        return ToolResult(True, out.strip() or f"FreeCAD macro finished: {macro}", data=data)
