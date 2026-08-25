from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult


def office_available() -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, "Office COM is only available on Windows"
    try:
        import win32com.client  # noqa: F401
    except Exception:
        return False, "pywin32 is not installed"
    roots = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft Office",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft Office",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft Office 16",
    ]
    if any(root.exists() for root in roots):
        return True, "Microsoft Office appears to be installed"
    return False, "Microsoft Office does not appear to be installed"


def _dispatch(progid: str):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    return win32com.client.Dispatch(progid)


class OfficeTool(Tool):
    name = "office"
    description = (
        "Read, create, and edit Microsoft Word, Excel, and PowerPoint documents via Windows COM "
        "when Office is installed. Always write to a new file unless the user asked for in-place edits. "
        "Use action=info to probe availability without launching Office."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "enum": ["word", "excel", "powerpoint"]},
            "action": {"type": "string", "enum": ["create", "read", "write", "save_as", "info"]},
            "path": {"type": "string"},
            "content": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["app", "action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        app = (kwargs.get("app") or "").lower()
        action = kwargs.get("action")
        available, detail = office_available()
        if action == "info":
            return ToolResult(available, detail, data={"available": available, "app": app})
        if not available:
            return ToolResult(False, "", error=f"Office automation unavailable: {detail}")
        try:
            if app == "word":
                word = _dispatch("Word.Application")
                word.Visible = False
                if action == "create":
                    doc = word.Documents.Add()
                    if kwargs.get("content"):
                        doc.Range().Text = kwargs["content"]
                    dest = kwargs.get("destination") or kwargs.get("path")
                    if not dest:
                        word.Quit()
                        return ToolResult(False, "", error="destination required")
                    Path(dest).parent.mkdir(parents=True, exist_ok=True)
                    doc.SaveAs(str(Path(dest).resolve()))
                    doc.Close()
                    word.Quit()
                    return ToolResult(True, f"Created Word document {dest}")
                if action == "read":
                    doc = word.Documents.Open(str(Path(kwargs["path"]).resolve()))
                    text = doc.Range().Text
                    doc.Close(False)
                    word.Quit()
                    return ToolResult(True, text)
                if action in {"write", "save_as"}:
                    src = Path(kwargs["path"]).resolve()
                    dest = Path(kwargs.get("destination") or kwargs["path"]).resolve()
                    doc = word.Documents.Open(str(src))
                    if kwargs.get("content"):
                        doc.Range().Text = kwargs["content"]
                    doc.SaveAs(str(dest))
                    doc.Close()
                    word.Quit()
                    return ToolResult(True, f"Saved {dest}")
                word.Quit()
            if app == "excel":
                excel = _dispatch("Excel.Application")
                excel.Visible = False
                excel.DisplayAlerts = False
                if action == "create":
                    dest = kwargs.get("destination") or kwargs.get("path")
                    if not dest:
                        excel.Quit()
                        return ToolResult(False, "", error="destination required")
                    wb = excel.Workbooks.Add()
                    Path(dest).parent.mkdir(parents=True, exist_ok=True)
                    wb.SaveAs(str(Path(dest).resolve()))
                    wb.Close()
                    excel.Quit()
                    return ToolResult(True, f"Created workbook {dest}")
                if action == "read":
                    wb = excel.Workbooks.Open(str(Path(kwargs["path"]).resolve()))
                    sheet = wb.Worksheets(1)
                    used = sheet.UsedRange
                    rows = []
                    for row in used.Value or []:
                        rows.append("\t".join("" if c is None else str(c) for c in (row if isinstance(row, tuple) else (row,))))
                    wb.Close(False)
                    excel.Quit()
                    return ToolResult(True, "\n".join(rows))
                excel.Quit()
            if app == "powerpoint":
                ppt = _dispatch("PowerPoint.Application")
                if action == "create":
                    dest = kwargs.get("destination") or kwargs.get("path")
                    if not dest:
                        ppt.Quit()
                        return ToolResult(False, "", error="destination required")
                    pres = ppt.Presentations.Add()
                    Path(dest).parent.mkdir(parents=True, exist_ok=True)
                    pres.SaveAs(str(Path(dest).resolve()))
                    pres.Close()
                    ppt.Quit()
                    return ToolResult(True, f"Created presentation {dest}")
                ppt.Quit()
            return ToolResult(False, "", error="Office action not supported or Office is not installed")
        except Exception as exc:
            return ToolResult(False, "", error=f"Office automation unavailable: {exc}")
