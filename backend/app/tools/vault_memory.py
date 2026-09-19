"""RFC-0107: Search and act on the bound Obsidian vault from agent turns."""

from __future__ import annotations

from typing import Any, Literal

from .base import RiskLevel, Tool, ToolResult


class VaultMemoryTool(Tool):
    name = "vault_memory"
    description = (
        "Search, read, and write the owner's bound Obsidian vault (Markdown + wiki-links). "
        "Use for durable project/decision notes — not for stuffing the whole vault into chat. "
        "Writes create or append jarvis_managed notes only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "read", "create", "append"],
                "description": "search: lexical hits; read: full note; create/append: managed notes.",
            },
            "query": {
                "type": "string",
                "description": "Search query (search action) or context label (optional).",
            },
            "rel_path": {
                "type": "string",
                "description": "Vault-relative path for read/create/append (e.g. Projects/foo.md).",
            },
            "content": {
                "type": "string",
                "description": "Markdown body for create/append.",
            },
        },
        "required": ["action"],
    }
    risk = RiskLevel.MEDIUM

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ..memory.obsidian_vault import (
            append_note,
            create_note,
            public_binding_status,
            read_note,
            search_vault,
        )

        if not public_binding_status().get("bound"):
            return ToolResult(
                False,
                "",
                error="No Obsidian vault is bound. Bind a folder in Settings → Integrations.",
            )

        action: Literal["search", "read", "create", "append"] = str(kwargs.get("action") or "search").strip().lower()  # type: ignore[assignment]
        query = str(kwargs.get("query") or "").strip()
        rel_path = str(kwargs.get("rel_path") or "").strip().replace("\\", "/")
        content = str(kwargs.get("content") or "").strip()

        try:
            if action == "search":
                if not query:
                    return ToolResult(False, "", error="query is required for search")
                hits = search_vault(query, limit=8)
                if not hits:
                    return ToolResult(True, "No vault notes matched that query.", data={"hits": []})
                lines = []
                payload = []
                for hit in hits:
                    lines.append(
                        f"- [{hit.rel_path}] {hit.title}: {hit.excerpt[:320]} (hash:{hit.content_hash[:12]})"
                    )
                    payload.append(
                        {
                            "rel_path": hit.rel_path,
                            "title": hit.title,
                            "excerpt": hit.excerpt,
                            "content_hash": hit.content_hash,
                        }
                    )
                return ToolResult(True, "\n".join(lines), data={"hits": payload})

            if action == "read":
                if not rel_path:
                    return ToolResult(False, "", error="rel_path is required for read")
                note = read_note(rel_path)
                body = str(note.get("body") or note.get("content") or "")
                if len(body) > 12000:
                    body = body[:12000] + "\n...[truncated]..."
                return ToolResult(
                    True,
                    body,
                    data={
                        "rel_path": note.get("rel_path"),
                        "content_hash": note.get("content_hash"),
                    },
                )

            if action == "create":
                if not rel_path or not content:
                    return ToolResult(False, "", error="rel_path and content are required for create")
                result = create_note(rel_path, content, jarvis_managed=True)
                return ToolResult(
                    True,
                    f"Created managed note {result['rel_path']}",
                    data=result,
                )

            if action == "append":
                if not rel_path or not content:
                    return ToolResult(False, "", error="rel_path and content are required for append")
                result = append_note(rel_path, content)
                if not result.get("ok"):
                    conflict = result.get("conflict") or {}
                    return ToolResult(
                        False,
                        "",
                        error=str(conflict.get("message") or "Append conflict — owner edits win."),
                        data={"conflict": conflict},
                    )
                return ToolResult(
                    True,
                    f"Appended to {result.get('rel_path')}",
                    data=result,
                )

            return ToolResult(False, "", error=f"Unsupported action: {action}")
        except FileNotFoundError as exc:
            return ToolResult(False, "", error=str(exc))
        except FileExistsError as exc:
            return ToolResult(False, "", error=str(exc))
        except ValueError as exc:
            return ToolResult(False, "", error=str(exc))
