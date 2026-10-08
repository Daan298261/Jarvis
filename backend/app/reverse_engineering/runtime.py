from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from . import provision, store
from .skill import guide
from .artifacts import BUILTIN_SCHEMAS

# Admission is independent of descriptions or untrusted MCP annotations.
STATIC_OPERATIONS = frozenset("""
open_binary close_binary binary_session binary_overview inspect_artifact extract_artifact
inspect_managed_artifact inspect_managed_members inspect_managed_native_boundaries
plan_managed_runtime_correlation project_managed_application_graph
analyze_javascript_application trace_application_feature trace_javascript_semantics
reconcile_javascript_runtime list_documents list_names list_procedures list_segments
list_strings search_strings search_procedures procedure_address procedure_assembly
procedure_callees procedure_callers procedure_info procedure_pseudo_code
read_function_instructions read_bytes address_to_file_offset procedure_references
resolve_containing_procedure xrefs batch_decompile get_call_graph find_xrefs_to_name
analyze_function inspect_native_api trace_feature find_code_for_string trace_call_path
get_evidence_bundle get_navigation_context inspect_address_context list_unknowns
record_unknown update_unknown verify_unknown_resolution evaluate_reconstruction_coverage
build_reconstruction_obligation_ledger inspect_native_dispatch_metadata trace_native_ui_action
list_browser_targets inspect_web_page analyze_web_bundle observe_web_session
discover_webmcp_tools capture_web_screenshot list_electron_targets inspect_electron_page
list_javascript_runtime_targets observe_javascript_runtime
""".split())
RUNTIME_OPERATIONS = frozenset("""
capture_process_scenario capture_browser_scenario capture_electron_scenario
run_controlled_replay prepare_node_characterization execute_node_characterization
android_capture
""".split())


def approval_target(arguments: dict) -> str:
    relevant = {k: arguments.get(k) for k in ("action", "investigation_id", "operation", "arguments")}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def requires_runtime_approval(arguments: dict) -> bool:
    return arguments.get("action") == "call" and arguments.get("operation") in RUNTIME_OPERATIONS


class SessionActor:
    """All MCP enter/call/exit operations live in one task (AnyIO cancel-scope ownership)."""

    def __init__(self, row: dict | None = None):
        self.row = row or {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.tools: dict[str, dict] = {}
        self.ready = asyncio.get_running_loop().create_future()
        self.worker = asyncio.create_task(self._run())

    async def _run(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        active = None
        try:
            async with AsyncExitStack() as stack:
                args = ["-d", provision.DISTRO, "-u", "root", "--exec", "/opt/anzu/bin/rea", "mcp"]
                env = dict(os.environ)
                if self.row.get("kind") == "browser":
                    command = provision.host_node()
                    args = [str(provision.runtime_root() / "host" / "node_modules" / "rea-agents" / "scripts" / "rea.mjs"), "mcp"]
                    env.update(REA_BROWSER_OBSERVE_ENABLED="true",
                               REA_BROWSER_CDP_ENDPOINTS_JSON=json.dumps([self.row["snapshot"]]),
                               REA_BROWSER_ALLOWED_ORIGINS_JSON=json.dumps(self.row.get("origins", [])),
                               REA_BROWSER_SCENARIO_ENABLED="true",
                               REA_BROWSER_SCENARIO_CDP_ENDPOINTS_JSON=json.dumps([self.row["snapshot"]]),
                               REA_BROWSER_SCENARIO_ALLOWED_ORIGINS_JSON=json.dumps(self.row.get("origins", [])))
                else:
                    command = "wsl.exe"
                    if self.row:
                        workspace = await asyncio.to_thread(provision.linux_path, str(store.directory(self.row["id"])))
                        # The adapter, not MCP annotations, admits runtime operations after
                        # an exact-action grant. Provider policy remains constrained to copies.
                        args = ["-d", provision.DISTRO, "-u", "root", "--exec", "env",
                                "REA_PROCESS_CAPTURE_ENABLED=true",
                                "REA_PROCESS_CAPTURE_AUTO_GRANT=true",
                                "REA_PROCESS_ALLOW_EXTERNAL_NETWORK=false",
                                "REA_PROCESS_EXECUTABLE_ROOTS_JSON=" + json.dumps([workspace]),
                                "REA_PROCESS_WORKING_ROOTS_JSON=" + json.dumps([workspace]),
                                "/opt/anzu/bin/rea", "mcp"]
                params = StdioServerParameters(command=command, args=args, env=env)
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await asyncio.wait_for(session.initialize(), 60)
                listing = await session.list_tools()
                self.tools = {t.name: t.model_dump(mode="json", by_alias=True) for t in listing.tools}
                self.ready.set_result(True)
                while True:
                    active = await self.queue.get()
                    if active is None:
                        break
                    name, args, future = active
                    try:
                        result = await session.call_tool(name, args)
                        if not future.done():
                            future.set_result(result.model_dump(mode="json", by_alias=True))
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
                    active = None
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(RuntimeError(str(exc)))
            if active is not None and not active[2].done():
                active[2].set_exception(RuntimeError("Analysis session stopped"))
        finally:
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[2].done():
                    item[2].set_exception(RuntimeError("Analysis session stopped"))

    async def call(self, name: str, arguments: dict) -> dict:
        await self.ready
        if self.worker.done():
            raise RuntimeError("Analysis session closed")
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((name, arguments, future))
        try:
            return await asyncio.wait_for(future, 600)
        except (TimeoutError, asyncio.CancelledError):
            await self.close(cancel=True)
            raise

    async def close(self, cancel=False):
        if cancel:
            self.worker.cancel()
        else:
            await self.queue.put(None)
        try:
            await asyncio.wait_for(asyncio.shield(self.worker), 20)
        except (TimeoutError, asyncio.CancelledError):
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)


class Investigations:
    def __init__(self):
        self.sessions: dict[str, SessionActor] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.active: dict[str, asyncio.Task] = {}

    async def actor(self, ident: str) -> SessionActor:
        actor = self.sessions.get(ident)
        if actor is None or actor.worker.done():
            if provision.state().get("status") != "ready":
                raise RuntimeError("Analysis engine is not ready. Open Settings > Integrations > Reverse Engineering.")
            row = store.load(ident)
            actor = SessionActor(row)
            self.sessions[ident] = actor
            await actor.ready
            if row.get("opened") and row["kind"] not in {"browser", "source"}:
                snapshot = await asyncio.to_thread(provision.linux_path, row["snapshot"])
                resumed = await actor.call("inspect_managed_artifact" if row["kind"] == "managed" else "open_binary", {"path": snapshot})
                if resumed.get("isError") or resumed.get("is_error"):
                    await actor.close(cancel=True)
                    raise RuntimeError("Saved target could not be reopened; prepare a new investigation")
        return actor

    async def prepare(self, target: str, question: str, allowed: list[str], task_id: str | None,
                      origins: list[str] | None = None) -> dict:
        row = await asyncio.to_thread(store.prepare, target, question, allowed, task_id)
        if row["kind"] == "browser":
            from urllib.parse import urlparse
            for origin in origins or []:
                parsed = urlparse(origin)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
                    raise ValueError("Browser origins must be exact HTTP(S) origins")
            row["origins"] = origins or []
            store.save(row)
        return {**row, "source_files": [item["path"] for item in row.get("manifest", [])[:100]] if row["kind"] == "source" else [],
                "source_file_count": len(row.get("manifest", [])) if row["kind"] == "source" else 0,
                "skill": guide(row["kind"]), "workflow": (
            "Source target: call record_source with the snapshot-relative filename to save evidence, then report with its returned evidence_id. Ordinary filesystem reads do not create investigation evidence." if row["kind"] == "source"
            else "Use catalog for the exact schema, then call focused operations. Native/archive: open_binary first; "
                 "managed: inspect_managed_artifact; JavaScript: analyze_javascript_application; "
                 "browser: list_browser_targets. Target paths are translated by the adapter."
        )}

    def owned(self, ident: str, task_id: str | None) -> dict:
        row = store.load(ident)
        if task_id and row.get("task_id") and task_id != row["task_id"]:
            raise PermissionError("Investigation belongs to a different task")
        return row

    async def catalog(self, ident: str, task_id: str | None, operation: str = "") -> dict:
        row = self.owned(ident, task_id)
        if row["status"] in {"closed", "cancelled"}:
            raise ValueError("Investigation is closed")
        if row["kind"] == "source":
            return {"operations": [], "workflow": "Use normal repository tools; source evidence may be recorded with action=record_source."}
        actor = await self.actor(ident)
        tools = {k: v for k, v in actor.tools.items() if k in STATIC_OPERATIONS | RUNTIME_OPERATIONS}
        tools.update(BUILTIN_SCHEMAS)
        if row["kind"] == "mobile" and Path(row["target"]).suffix.lower() == ".apk":
            tools["android_decompile"] = {"name": "android_decompile", "inputSchema": {"type": "object", "properties": {}}}
            from .android import capture_schema
            tools["android_capture"] = capture_schema()
        if operation:
            if operation not in tools:
                raise ValueError("Operation is unavailable in the advertised session catalog")
            return tools[operation]
        return {"operations": [{"name": name, "description": tool.get("description", "")[:250],
                                "requires_approval": name in RUNTIME_OPERATIONS} for name, tool in tools.items()]}

    async def _map_arguments(self, row: dict, arguments: dict) -> dict:
        # Never admit arbitrary secondary targets or output paths outside the investigation.
        base = store.directory(row["id"]).resolve()
        snapshot = Path(row["snapshot"]) if row["kind"] != "browser" else None
        path_keys = {"path", "file_path", "binary_path", "snapshot_path", "output_path", "app_path", "root_path",
                     "artifact_path", "asar_path", "directory", "source_path", "working_directory", "cwd", "executable", "input_path"}
        endpoint_keys = {"endpoint", "cdp_endpoint", "inspector_endpoint"}

        async def walk(value, key=""):
            if key == "allowed_origins" and isinstance(value, list):
                if any(origin not in row.get("origins", []) for origin in value):
                    raise PermissionError("Origins must stay within the prepared browser scope")
            if isinstance(value, dict):
                return {k: await walk(v, k) for k, v in value.items()}
            if isinstance(value, list):
                return [await walk(v, key) for v in value]
            if (key in endpoint_keys or key.endswith("_endpoint")) and isinstance(value, str):
                if row["kind"] != "browser" or value != row["snapshot"]:
                    raise PermissionError("Endpoint must match the prepared browser target")
            if (key in path_keys or key.endswith("_path")) and isinstance(value, str):
                candidate = snapshot if snapshot and value in {row["target"], row["snapshot"]} else Path(value).resolve()
                if candidate is None or not candidate.resolve().is_relative_to(base):
                    raise PermissionError(f"{key} must remain inside the prepared investigation")
                return await asyncio.to_thread(provision.linux_path, str(candidate))
            if key == "native_mount_approved" and value:
                raise PermissionError("DMG mounting is not admitted on this host")
            return value
        return await walk(arguments)

    async def call(self, ident: str, operation: str, arguments: dict, task_id: str | None,
                   grant_id: str | None = None) -> dict:
        lock = self.locks.setdefault(ident, asyncio.Lock())
        async with lock:
            row = self.owned(ident, task_id)
            if row["status"] in {"cancelled", "closed"}:
                raise ValueError("Investigation is closed; prepare a new target")
            await asyncio.to_thread(store.validate_snapshot, row)
            if operation not in STATIC_OPERATIONS | RUNTIME_OPERATIONS | {"android_decompile"} | BUILTIN_SCHEMAS.keys():
                raise PermissionError("Operation is not admitted")
            from ..policy.action_gate import gate_side_effect
            params = {"action": "call", "investigation_id": ident, "operation": operation, "arguments": arguments}
            decision = gate_side_effect("reverse_engineer", arguments=params, task_id=task_id, grant_id=grant_id)
            if not decision.allowed:
                return {"status": "pending_approval" if decision.requires_approval else "denied",
                        "pending_id": decision.pending_approval_id, "reason": decision.reason}
            if operation in RUNTIME_OPERATIONS:
                from ..policy.approval_grant import consume_grant
                consume_grant(grant_id)
            row["status"] = "analyzing"
            store.save(row)
            self.active[ident] = asyncio.current_task()
            try:
                if operation in BUILTIN_SCHEMAS:
                    from jsonschema import validate
                    from .artifacts import materialize, read_source
                    validate(arguments, BUILTIN_SCHEMAS[operation]["inputSchema"])
                    result = await (materialize(row) if operation == "materialize_artifact" else read_source(row, arguments))
                elif operation in {"android_capture", "android_decompile"}:
                    from .android import capture, decompile
                    result = await (capture(row, arguments) if operation == "android_capture" else decompile(row))
                else:
                    actor = await self.actor(ident)
                    if operation not in actor.tools:
                        raise ValueError("Provider does not advertise this operation")
                    mapped = await self._map_arguments(row, arguments)
                    # Validate the real schema before any provider operation.
                    from jsonschema import validate
                    validate(mapped, actor.tools[operation]["inputSchema"])
                    result = await actor.call(operation, mapped)
                    if operation in {"open_binary", "inspect_managed_artifact"} and not (result.get("isError") or result.get("is_error")):
                        row["opened"] = True
                    elif operation == "close_binary":
                        row["opened"] = False
                return self.record(row, operation, arguments, result)
            except BaseException as exc:
                row.update(status="interrupted", last_error=str(exc)[:2000])
                store.save(row)
                raise
            finally:
                self.active.pop(ident, None)

    def record(self, row: dict, operation: str, arguments: dict, result: dict) -> dict:
        evidence_id = f"E{len(row['evidence']) + 1:05d}"
        entry = {"id": evidence_id, "operation": operation, "arguments": arguments,
                 "target_sha256": row.get("sha256"), "result": result,
                 "success": not bool(result.get("isError") or result.get("is_error"))}
        p = store.directory(row["id"]) / "evidence"
        p.mkdir(mode=0o700, exist_ok=True)
        store.atomic_json(p / f"{evidence_id}.json", entry)
        row["evidence"].append({"id": evidence_id, "operation": operation, "success": entry["success"]})
        row["status"] = "investigating"
        store.save(row)
        return {**entry, "status": "evidence" if entry["success"] else "analysis_failed",
                "reason": "" if entry["success"] else "Provider rejected the operation; inspect saved error evidence"}

    async def report(self, ident: str, findings: list[dict], unknowns: list[str], task_id: str | None):
        async with self.locks.setdefault(ident, asyncio.Lock()):
            row = self.owned(ident, task_id)
            if row["status"] == "cancelled":
                raise ValueError("Investigation was cancelled")
            await asyncio.to_thread(store.validate_snapshot, row)
            return await asyncio.to_thread(store.write_report, row, findings, unknowns)

    async def record_source(self, ident: str, args: dict, task_id: str | None):
        async with self.locks.setdefault(ident, asyncio.Lock()):
            row = self.owned(ident, task_id)
            if row["kind"] != "source" or row["status"] in {"closed", "cancelled"}:
                raise ValueError("Source evidence requires an open source investigation")
            await asyncio.to_thread(store.validate_snapshot, row)
            snapshot = Path(row["snapshot"]).resolve()
            relative = args["path"]
            path = (snapshot / relative).resolve() if snapshot.is_dir() else snapshot
            if (snapshot.is_dir() and not path.is_relative_to(snapshot)) or (snapshot.is_file() and relative not in {"", ".", snapshot.name, row["target"], row["snapshot"]}):
                raise PermissionError("Source path escapes target")
            if path.stat().st_size > 2 * 1024**2:
                raise ValueError("Source file exceeds 2 MiB read limit")
            lines = path.read_text(encoding="utf-8").splitlines()
            start, end = int(args.get("start", 1)), int(args.get("end", min(len(lines), 500)))
            if start < 1 or end < start or end > len(lines) or end - start >= 2000:
                raise ValueError("Select a valid range of at most 2000 source lines")
            return self.record(row, "source_read", args, {"path": relative, "start": start, "end": end,
                                                        "text": "\n".join(lines[start-1:end])})

    async def close(self, ident: str, task_id: str | None, cancelled=False) -> dict:
        self.owned(ident, task_id)
        active = self.active.get(ident)
        if active and active is not asyncio.current_task():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        actor = self.sessions.pop(ident, None)
        if actor:
            await actor.close(cancel=cancelled)
        # Re-read after an interrupted call persisted its state.
        async with self.locks.setdefault(ident, asyncio.Lock()):
            row = store.load(ident)
            row["status"] = "cancelled" if cancelled else "closed"
            return store.save(row)

    async def release_task(self, task_id: str, cancelled=False):
        for row in store.list_rows(task_id):
            active = self.active.get(row["id"])
            if active and active is not asyncio.current_task():
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
            actor = self.sessions.pop(row["id"], None)
            if actor:
                await actor.close(cancel=True)
            if cancelled and row["status"] not in {"reported", "partial", "closed", "cancelled"}:
                current = store.load(row["id"])
                current["status"] = "cancelled"
                store.save(current)

    async def shutdown(self):
        active = [t for t in self.active.values() if t is not asyncio.current_task()]
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        await asyncio.gather(*(a.close(cancel=True) for a in list(self.sessions.values())), return_exceptions=True)
        self.sessions.clear()


SERVICE = Investigations()
