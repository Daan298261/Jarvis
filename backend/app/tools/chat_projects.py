from __future__ import annotations

from typing import Any

from ..projects import portal_store
from .base import RiskLevel, Tool, ToolResult


class ChatProjectsTool(Tool):
    name = "chat_projects"
    description = (
        "List and organize portal projects and saved chats on the Leader. "
        "Actions: list_projects, list_conversations, open_conversation, move_conversation, move_task."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_projects",
                    "list_conversations",
                    "open_conversation",
                    "move_conversation",
                    "move_task",
                ],
            },
            "project_id": {"type": "string"},
            "conversation_id": {"type": "string"},
            "task_id": {"type": "string"},
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "list_projects":
            rows = await portal_store.list_projects()
            lines = [
                f"{row['id']}: {row['name']} ({len(row.get('taskIds') or [])} tasks, {len(row.get('conversationIds') or [])} chats)"
                for row in rows
            ]
            return ToolResult(True, "\n".join(lines) if lines else "No projects.", data={"projects": rows})
        if action == "list_conversations":
            project_id = str(kwargs.get("project_id") or "").strip()
            if not project_id:
                return ToolResult(False, "", error="project_id is required")
            rows = await portal_store.list_projects()
            match = next((row for row in rows if row["id"] == project_id), None)
            if not match:
                return ToolResult(False, "", error="Project not found")
            ids = match.get("conversationIds") or []
            return ToolResult(True, "\n".join(ids) if ids else "No chats in project.", data={"conversationIds": ids})
        if action == "open_conversation":
            conversation_id = str(kwargs.get("conversation_id") or "").strip()
            if not conversation_id:
                return ToolResult(False, "", error="conversation_id is required")
            detail = await portal_store.open_conversation(conversation_id)
            if not detail:
                return ToolResult(False, "", error="Conversation not found")
            return ToolResult(True, detail.get("title") or conversation_id, data=detail)
        if action == "move_conversation":
            conversation_id = str(kwargs.get("conversation_id") or "").strip()
            project_id = str(kwargs.get("project_id") or "").strip()
            if not conversation_id:
                return ToolResult(False, "", error="conversation_id is required")
            if project_id:
                await portal_store.link_member(project_id, "owner_chat", conversation_id)
            else:
                await portal_store.unlink_member("owner_chat", conversation_id)
            return ToolResult(True, f"conversation {conversation_id} -> project {project_id or 'none'}")
        if action == "move_task":
            task_id = str(kwargs.get("task_id") or "").strip()
            project_id = str(kwargs.get("project_id") or "").strip()
            if not task_id:
                return ToolResult(False, "", error="task_id is required")
            if project_id:
                await portal_store.link_member(project_id, "task", task_id)
            else:
                await portal_store.unlink_member("task", task_id)
            return ToolResult(True, f"task {task_id} -> project {project_id or 'none'}")
        return ToolResult(False, "", error=f"Unknown action {action}")
