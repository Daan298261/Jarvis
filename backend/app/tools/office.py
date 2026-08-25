from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult

_PROGID = {
    "word": "Word.Application",
    "excel": "Excel.Application",
    "powerpoint": "PowerPoint.Application",
}


def office_runtime_available() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
    except Exception:
        return False
    return True


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
        "action=info reports availability without launching Office."
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
        if app not in _PROGID:
            return ToolResult(False, "", error="app must be word, excel, or powerpoint")
        if action == "info":
            available = office_runtime_available()
            return ToolResult(
                True,
                f"app={app} progid={_PROGID[app]} available={available} "
                f"platform={platform.system()} dispatch=false",
                data={"app": app, "available": available, "dispatch": False},
            )
        if not office_runtime_available():
            return ToolResult(False, "", error="Office automation unavailable on this machine")
        try:
            if app == "word":
                return await self._word(action, kwargs)
            if app == "excel":
                return await self._excel(action, kwargs)
            return await self._powerpoint(action, kwargs)
        except Exception as exc:
            return ToolResult(False, "", error=f"Office automation unavailable: {exc}")

    async def _word(self, action: str, kwargs: dict[str, Any]) -> ToolResult:
        word = _dispatch("Word.Application")
        word.Visible = False
        try:
            if action == "create":
                dest = kwargs.get("destination") or kwargs.get("path")
                if not dest:
                    return ToolResult(False, "", error="destination required")
                doc = word.Documents.Add()
                if kwargs.get("content"):
                    doc.Range().Text = kwargs["content"]
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                doc.SaveAs(str(Path(dest).resolve()))
                doc.Close()
                return ToolResult(True, f"Created Word document {dest}")
            if action == "read":
                doc = word.Documents.Open(str(Path(kwargs["path"]).resolve()))
                text = doc.Range().Text
                doc.Close(False)
                return ToolResult(True, text)
            if action in {"write", "save_as"}:
                src = Path(kwargs["path"]).resolve()
                dest = Path(kwargs.get("destination") or kwargs["path"]).resolve()
                doc = word.Documents.Open(str(src))
                if kwargs.get("content"):
                    doc.Range().Text = kwargs["content"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                doc.SaveAs(str(dest))
                doc.Close()
                return ToolResult(True, f"Saved {dest}")
            return ToolResult(False, "", error="Office action not supported or Office is not installed")
        finally:
            word.Quit()

    async def _excel(self, action: str, kwargs: dict[str, Any]) -> ToolResult:
        excel = _dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        try:
            if action == "create":
                dest = kwargs.get("destination") or kwargs.get("path")
                if not dest:
                    return ToolResult(False, "", error="destination required")
                wb = excel.Workbooks.Add()
                if kwargs.get("content"):
                    sheet = wb.Worksheets(1)
                    sheet.Cells(1, 1).Value = kwargs["content"]
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                wb.SaveAs(str(Path(dest).resolve()))
                wb.Close()
                return ToolResult(True, f"Created workbook {dest}")
            if action == "read":
                wb = excel.Workbooks.Open(str(Path(kwargs["path"]).resolve()))
                sheet = wb.Worksheets(1)
                used = sheet.UsedRange
                rows = []
                for row in used.Value or []:
                    rows.append("\t".join("" if c is None else str(c) for c in (row if isinstance(row, tuple) else (row,))))
                wb.Close(False)
                return ToolResult(True, "\n".join(rows))
            if action in {"write", "save_as"}:
                src = Path(kwargs["path"]).resolve()
                dest = Path(kwargs.get("destination") or kwargs["path"]).resolve()
                wb = excel.Workbooks.Open(str(src))
                if kwargs.get("content"):
                    wb.Worksheets(1).Cells(1, 1).Value = kwargs["content"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                wb.SaveAs(str(dest))
                wb.Close()
                return ToolResult(True, f"Saved {dest}")
            return ToolResult(False, "", error="Office action not supported or Office is not installed")
        finally:
            excel.Quit()

    async def _powerpoint(self, action: str, kwargs: dict[str, Any]) -> ToolResult:
        ppt = _dispatch("PowerPoint.Application")
        try:
            if action == "create":
                dest = kwargs.get("destination") or kwargs.get("path")
                if not dest:
                    return ToolResult(False, "", error="destination required")
                pres = ppt.Presentations.Add()
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                pres.SaveAs(str(Path(dest).resolve()))
                pres.Close()
                return ToolResult(True, f"Created presentation {dest}")
            if action == "read":
                pres = ppt.Presentations.Open(str(Path(kwargs["path"]).resolve()), WithWindow=False)
                texts = []
                for slide in pres.Slides:
                    for shape in slide.Shapes:
                        if shape.HasTextFrame and shape.TextFrame.HasText:
                            texts.append(shape.TextFrame.TextRange.Text)
                pres.Close()
                return ToolResult(True, "\n".join(texts))
            if action in {"write", "save_as"}:
                src = Path(kwargs["path"]).resolve()
                dest = Path(kwargs.get("destination") or kwargs["path"]).resolve()
                pres = ppt.Presentations.Open(str(src), WithWindow=False)
                dest.parent.mkdir(parents=True, exist_ok=True)
                pres.SaveAs(str(dest))
                pres.Close()
                return ToolResult(True, f"Saved {dest}")
            return ToolResult(False, "", error="Office action not supported or Office is not installed")
        finally:
            ppt.Quit()
