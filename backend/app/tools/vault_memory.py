"""RFC-0107: Search and act on the bound Obsidian vault from agent turns."""

from __future__ import annotations

from typing import Any, Literal

from .base import RiskLevel, Tool, ToolResult


class VaultMemoryTool(Tool):
    name = "vault_memory"
    description = (
        "Search, read, resolve wiki-links, follow hop-capped neighborhoods, and write the "
        "owner's bound Obsidian vault (Markdown + wiki-links). Use for durable project/"
        "decision notes — not for stuffing the whole vault into chat. Writes create or "
        "append jarvis_managed notes only (with optional memory/task pointer)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "read", "create", "append", "edit", "resolve", "neighborhood", "follow"],
                "description": (
                    "search: lexical hits; read: full note; create/append/edit: managed notes; "
                    "resolve: wiki-link → path; neighborhood/follow: hop-capped graph."
                ),
            },
            "query": {
                "type": "string",
                "description": "Search query, wiki-link text (resolve/follow), or context label.",
            },
            "rel_path": {
                "type": "string",
                "description": "Vault-relative path for read/create/append/edit/neighborhood.",
            },
            "content": {
                "type": "string",
                "description": "Markdown body for create/append/edit.",
            },
            "hops": {
                "type": "integer",
                "description": "Neighborhood hop cap (default 1, max 2).",
            },
            "memory_pointer": {
                "type": "string",
                "description": "Optional memory/task id stored on jarvis_managed create.",
            },
            "force": {
                "type": "boolean",
                "description": "Force edit even when owner edits conflict (default false).",
            },
        },
        "required": ["action"],
    }
    risk = RiskLevel.MEDIUM

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ..memory.obsidian_vault import (
            act_vault,
            append_note,
            create_note,
            edit_note,
            follow_wiki_link,
            neighborhood,
            public_binding_status,
            read_note,
            resolve_wiki_link,
            search_vault,
            vault_root,
        )

        if vault_root() is None or not public_binding_status().get("bound"):
            return ToolResult(
                False,
                "",
                error="No Obsidian vault is bound. Bind a folder in Settings → Integrations.",
            )

        action = str(kwargs.get("action") or "search").strip().lower()
        query = str(kwargs.get("query") or "").strip()
        rel_path = str(kwargs.get("rel_path") or "").strip().replace("\\", "/")
        content = str(kwargs.get("content") or "").strip()
        memory_pointer = str(kwargs.get("memory_pointer") or "").strip() or None
        force = bool(kwargs.get("force") or False)
        try:
            hops = int(kwargs.get("hops") or 1)
        except (TypeError, ValueError):
            hops = 1

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
                    heading = hit.heading or hit.title
                    lines.append(
                        f"- [{hit.rel_path}#{heading}] {hit.excerpt[:320]} "
                        f"(hash:{hit.content_hash[:12]}; provenance:{hit.provenance})"
                    )
                    payload.append(
                        {
                            "rel_path": hit.rel_path,
                            "title": hit.title,
                            "heading": hit.heading,
                            "excerpt": hit.excerpt,
                            "content_hash": hit.content_hash,
                            "provenance": hit.provenance,
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
                result = create_note(
                    rel_path,
                    content,
                    jarvis_managed=True,
                    memory_pointer=memory_pointer,
                )
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

            if action == "edit":
                if not rel_path or not content:
                    return ToolResult(False, "", error="rel_path and content are required for edit")
                result = edit_note(rel_path, content, force=force)
                if not result.get("ok"):
                    conflict = result.get("conflict") or {}
                    return ToolResult(
                        False,
                        "",
                        error=str(conflict.get("message") or "Edit conflict — owner edits win."),
                        data={"conflict": conflict},
                    )
                return ToolResult(True, f"Edited {result.get('rel_path')}", data=result)

            if action == "resolve":
                link = query or rel_path
                if not link:
                    return ToolResult(False, "", error="query (wiki-link) is required for resolve")
                resolved = resolve_wiki_link(link, rel_path if query else "")
                if resolved.broken:
                    return ToolResult(
                        True,
                        f"Broken wiki-link: [[{link}]]",
                        data={
                            "link": link,
                            "broken": True,
                            "target_path": resolved.target_path,
                            "heading": resolved.heading,
                        },
                    )
                return ToolResult(
                    True,
                    f"Resolved [[{link}]] → {resolved.target_path}"
                    + (f"#{resolved.heading}" if resolved.heading else ""),
                    data={
                        "link": link,
                        "broken": False,
                        "target_path": resolved.target_path,
                        "heading": resolved.heading,
                        "via_id": resolved.via_id,
                    },
                )

            if action == "neighborhood":
                if not rel_path:
                    return ToolResult(False, "", error="rel_path is required for neighborhood")
                hood = neighborhood(rel_path, hops=max(0, min(hops, 2)))
                lines = [
                    f"- [{h.rel_path}#{h.heading or h.title}] {h.excerpt[:200]} (hash:{h.content_hash[:12]})"
                    for h in hood
                ]
                return ToolResult(
                    True,
                    "\n".join(lines) if lines else "No neighborhood notes.",
                    data={
                        "rel_path": rel_path,
                        "hops": hops,
                        "hits": [
                            {
                                "rel_path": h.rel_path,
                                "title": h.title,
                                "heading": h.heading,
                                "excerpt": h.excerpt,
                                "content_hash": h.content_hash,
                            }
                            for h in hood
                        ],
                    },
                )

            if action == "follow":
                link = query or rel_path
                if not link:
                    return ToolResult(False, "", error="query (wiki-link) is required for follow")
                payload = follow_wiki_link(link, source_rel=rel_path if query else "", hops=hops)
                if payload.get("broken"):
                    return ToolResult(True, f"Broken wiki-link: [[{link}]]", data=payload)
                hood = payload.get("neighborhood") or []
                lines = [
                    f"- [{h['rel_path']}#{h.get('heading') or h.get('title')}] "
                    f"{(h.get('excerpt') or '')[:200]} (hash:{(h.get('content_hash') or '')[:12]})"
                    for h in hood
                ]
                return ToolResult(
                    True,
                    f"Followed [[{link}]] → {payload.get('target_path')}\n" + "\n".join(lines),
                    data=payload,
                )

            # Prefer act_vault for any future actions.
            result = act_vault(
                action,  # type: ignore[arg-type]
                rel_path=rel_path,
                content=content,
                query=query,
                force=force,
                hops=hops,
                memory_pointer=memory_pointer,
            )
            return ToolResult(True, str(result), data=result if isinstance(result, dict) else {})
        except FileNotFoundError as exc:
            return ToolResult(False, "", error=str(exc))
        except FileExistsError as exc:
            return ToolResult(False, "", error=str(exc))
        except ValueError as exc:
            return ToolResult(False, "", error=str(exc))
