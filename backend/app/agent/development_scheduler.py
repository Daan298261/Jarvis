"""Owner-directed, revision-bound local development missions (RFC-0211)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import psutil
from pydantic import BaseModel, Field, model_validator

from ..config import data_dir, load_settings, repo_root
from .self_dev import kill_switch_active
from .worktrees import create_worktree, run_git


class DevelopmentConfig(BaseModel):
    enabled: bool = False
    away_mode: bool = False
    resource_hold: str = Field(default="", max_length=500)
    repo: str = ""
    base_ref: str = "development"
    interval_minutes: int = Field(default=60, ge=1, le=10080)
    max_run_minutes: int = Field(default=60, ge=1, le=720)
    failure_limit: int = Field(default=3, ge=1, le=10)
    ollama_url: str = "http://127.0.0.1:11434"
    coder_model: str = "anzu-coder-27b:latest"
    vision_model: str = "anzu-qwen-worker:latest"
    drive_folder_id: str = ""
    drive_search_tool: str = ""
    drive_fetch_tool: str = ""

    @model_validator(mode="after")
    def local_only(self):
        from urllib.parse import urlparse
        url = urlparse(self.ollama_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Ollama must use a local HTTP endpoint")
        if self.base_ref.startswith("-") or not re.fullmatch(r"[a-zA-Z0-9_./-]+", self.base_ref):
            raise ValueError("Invalid development base reference")
        if self.drive_folder_id and not re.fullmatch(r"[a-zA-Z0-9_-]+", self.drive_folder_id):
            raise ValueError("Invalid Drive folder id")
        return self


def root() -> Path:
    path = data_dir() / "development_scheduler"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def default_state():
    return {"config": DevelopmentConfig().model_dump(), "items": {}, "runs": [], "next_run": 0, "failures": 0, "error": "", "drive_status": "Not connected", "order": [], "order_revision": 0, "order_history": [], "owner_pins": []}


def source_item(source: str, title: str, content: str, url: str = "", path: str = ""):
    if not content.strip() or len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("RFC must contain text and fit within 1 MB")
    return {"id": hashlib.sha256(source.encode()).hexdigest()[:24], "source": source, "title": title[:300], "content": content, "revision": hashlib.sha256(content.encode()).hexdigest(), "url": url, "path": path}


def upsert(state, item):
    old = state["items"].get(item["id"], {})
    same = old.get("revision") == item["revision"]
    state["items"][item["id"]] = {**old, **item, "approved_revision": old.get("approved_revision", "") if same else "", "status": old.get("status", "available") if same else "available", "updated_at": time.time()}


def repo_items(config: DevelopmentConfig):
    repo = Path(config.repo or repo_root()).resolve()
    # Read from the same pinned Git revision the worker will receive, not dirty files.
    names = run_git(repo, ["ls-tree", "-r", "--name-only", config.base_ref, "docs/rfcs"]).stdout.splitlines()
    out = []
    identity = str(repo).casefold()
    for name in names:
        if not re.fullmatch(r"docs/rfcs/\d{4}-[^/]+\.md", name):
            continue
        content = run_git(repo, ["show", f"{config.base_ref}:{name}"]).stdout
        if re.search(r"(?im)^\s*(?:\*\*)?status(?:\*\*)?\s*:\s*(?:\*\*)?accepted\b", content):
            title = next((line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("# ")), name)
            out.append(source_item(f"repo:{identity}:{name}", title, content, path=name))
    return out


async def model_capabilities(config: DevelopmentConfig):
    result = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for role, model, required in (("coder", config.coder_model, {"tools"}), ("vision", config.vision_model, {"vision", "tools"})):
            response = await client.post(config.ollama_url.rstrip("/") + "/api/show", json={"model": model})
            response.raise_for_status()
            capabilities = set(response.json().get("capabilities", []))
            if not required <= capabilities:
                raise ValueError(f"{role} model {model} lacks {', '.join(sorted(required - capabilities))}")
            result[role] = {"model": model, "capabilities": sorted(capabilities)}
    return result


def mcp_payload(result):
    if not result.success:
        raise RuntimeError(result.error or result.output)
    data = result.data or {}
    if "structuredContent" in data:
        return data["structuredContent"]
    if data and ("files" in data or "content" in data):
        return data
    try:
        return json.loads(data.get("mcp_text", result.output))
    except json.JSONDecodeError:
        return {"content": data.get("mcp_text", result.output)}


class DevelopmentScheduler:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.runner = None
        self.process = None
        self.lease = None
        self.publication = None
        self.owner_agent = None

    def state(self):
        return read_json(root() / "state.json", default_state())

    def save(self, state):
        write_json(root() / "state.json", state)

    def ordered_items(self, state):
        order = state.get("order", [])
        return sorted(state["items"].values(), key=lambda item: (
            order.index(item["id"]) if item["id"] in order else len(order),
            item.get("priority", 3), item.get("updated_at", 0), item["id"]))

    async def enqueue_owner(self, task, agent):
        self.owner_agent = agent
        async with self.lock:
            state = self.state()
            old = state["items"].get(task.id, {})
            state["items"][task.id] = {**old, "id": task.id, "title": (task.title or task.prompt)[:300],
                "source": "owner_task", "revision": "", "approved_revision": "", "status": "queued", "updated_at": time.time()}
            self.save(state)
        await self.dispatch_owner()

    async def dispatch_owner(self):
        from ..db.models import Task
        from ..db.session import SessionLocal
        if self.owner_agent is None:
            from .loop import AGENT
            self.owner_agent = AGENT
        agent = self.owner_agent
        if kill_switch_active() or any(not task.done() for task in agent._tasks.values()):
            return
        async with self.lock:
            state = self.state()
            pending = [i for i in self.ordered_items(state) if i.get("source") == "owner_task" and i["status"] == "queued"]
            async with SessionLocal() as session:
                for item in pending:
                    task = await session.get(Task, item["id"])
                    if not task or task.status != "queued":
                        item["status"] = task.status if task else "unavailable"
                        continue
                    item["status"] = "dispatched"
                    self.save(state)
                    agent._start_runner(task.id, agent._run(task.id, continue_existing=False))
                    agent._tasks[task.id].add_done_callback(lambda _: asyncio.create_task(self.dispatch_owner()))
                    return
            self.save(state)

    async def upcoming(self):
        from ..db.models import Task
        from ..db.session import SessionLocal
        from sqlalchemy import select
        state = self.state()
        tasks = []
        async with SessionLocal() as session:
            rows = (await session.execute(select(Task).where(Task.status.in_(["queued", "running"])))) .scalars().all()
            tasks = [{"id": t.id, "title": t.title or t.prompt[:120], "status": t.status, "kind": "task"} for t in rows]
        items = [{**{k: v for k, v in i.items() if k != "content"}, "kind": "development"}
                 for i in self.ordered_items(state) if i.get("source") != "owner_task"
                 and i["status"] in {"queued", "running", "reviewing", "testing", "building"}]
        return {"items": tasks + items, "revision": state.get("order_revision", 0),
                "away_mode": bool(state["config"].get("away_mode")), "can_undo": bool(state.get("order_history"))}

    async def reorder(self, ids, revision, actor="owner", reason="Owner ordering", undo=False):
        async with self.lock:
            state = self.state()
            if revision != state.get("order_revision", 0):
                raise ValueError("Queue changed; refresh before reordering")
            pending = {i["id"] for i in state["items"].values() if i["status"] == "queued"}
            history = state.setdefault("order_history", [])
            old = state.setdefault("order", [])
            if actor != "owner" and any(i in state.get("owner_pins", []) for i in pending):
                raise ValueError("Owner ordering takes precedence over automatic reordering")
            if undo:
                if not history: raise ValueError("No queue change to undo")
                previous = history.pop()
                ids = [i for i in previous["order"] if i in pending]
                ids += sorted(i for i in pending if i not in ids)
                state["owner_pins"] = previous.get("pins", [])
            else:
                if len(ids) != len(set(ids)) or set(ids) != pending:
                    raise ValueError("Reorder must include each pending development task exactly once")
                if actor != "owner" and any(i in state.get("owner_pins", []) for i in pending):
                    raise ValueError("Owner ordering takes precedence over automatic reordering")
                history.append({"order": list(old), "pins": list(state.get("owner_pins", [])),
                                "actor": actor, "reason": reason[:500], "at": time.time()})
                del history[:-30]
                if actor == "owner": state["owner_pins"] = list(ids)
            state["order"] = ids
            state["order_revision"] = revision + 1
            self.save(state)
            return self.public(state)

    async def away(self, enabled):
        if os.environ.get("ANZU_DEVELOPMENT_MISSION"):
            raise ValueError("Coding workers cannot activate publication policy")
        if not enabled:
            await self.stop()
            async with self.lock:
                state = self.state(); state["config"]["away_mode"] = False
                self.save(state)
            return self.public(state)
        async with self.lock:
            if kill_switch_active(): raise ValueError("Emergency stop is active")
            state = self.state()
            repo = Path(state["config"].get("repo") or repo_root()).resolve()
            if not (repo / ".git").exists():
                choices = [Path.home() / "Documents/Projects/Jarvis/Jarvis", Path.home() / "Documents/Projects/ANZU/ANZU"]
                repo = next((p for p in choices if (p / ".git").exists()), repo)
            run_git(repo, ["rev-parse", "--git-dir"])
            state["config"].update(repo=str(repo), base_ref="origin/development", enabled=True, away_mode=True)
            state["authorization"] = {"actor": "owner", "scope": "development review merge and build", "at": time.time()}
            state["next_run"] = 0; state["failures"] = 0
            self.save(state)
        return self.public()

    async def publication_status(self, run_id, status, **values):
        async with self.lock:
            state = self.state(); run = next(r for r in state["runs"] if r["id"] == run_id)
            run.update(status=status, **values); self.save(state)

    async def configure(self, config: DevelopmentConfig):
        async with self.lock:
            state = self.state()
            if any(r["status"] == "running" for r in state["runs"]):
                raise ValueError("Stop the active mission before changing its configuration")
            state["config"] = config.model_dump()
            state["next_run"] = time.time() + config.interval_minutes * 60
            state["failures"] = 0
            state["error"] = ""
            self.save(state)
            return self.public(state)

    def public(self, state=None):
        state = state or self.state()
        runs = []
        for run in state["runs"][-30:]:
            view = dict(run)
            status = read_json(root() / run["id"] / "status.json", {})
            view["task"] = status
            runs.append(view)
        return {**state, "items": [{k: v for k, v in item.items() if k != "content"} for item in self.ordered_items(state)], "runs": runs, "emergency_stop": kill_switch_active()}

    async def import_drive(self, file_id: str, title: str, content: str):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", file_id):
            raise ValueError("Invalid Drive file identity")
        async with self.lock:
            state = self.state()
            upsert(state, source_item(f"drive:{file_id}", title, content, f"https://drive.google.com/file/d/{file_id}/view"))
            self.save(state)
            return self.public(state)

    async def scan(self):
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            items = await asyncio.to_thread(repo_items, config)
            found = {item["id"] for item in items}
            for old in state["items"].values():
                if old["source"].startswith("repo:") and old["id"] not in found:
                    old.update(status="unavailable", approved_revision="")
            for item in items:
                upsert(state, item)
            if config.drive_folder_id and config.drive_search_tool and config.drive_fetch_tool:
                try:
                    from ..tools.mcp_runtime import MCP
                    token = None
                    seen = set()
                    fetched = set()
                    while True:
                        args = {"item_type": "document", "topn": 100, "special_filter_query_str": f"'{config.drive_folder_id}' in parents"}
                        if token:
                            args["page_token"] = token
                        listing = mcp_payload(await asyncio.wait_for(MCP.call(config.drive_search_tool, args), 30))
                        rows = listing.get("files", listing.get("results", []))
                        if not isinstance(rows, list):
                            raise ValueError("Drive search must return files/results with id, name and url")
                        for row in rows:
                            file_id = str(row.get("id", ""))
                            title = str(row.get("name", row.get("title", "")))
                            if "rfc" not in title.lower() or "digest" in title.lower():
                                continue
                            if not re.fullmatch(r"[a-zA-Z0-9_-]+", file_id):
                                raise ValueError("Drive search returned an invalid file identity")
                            url = f"https://drive.google.com/file/d/{file_id}/view"
                            payload = mcp_payload(await asyncio.wait_for(MCP.call(config.drive_fetch_tool, {"url": url}), 30))
                            content = payload.get("content", payload.get("text", ""))
                            if not isinstance(content, str):
                                raise ValueError("Drive fetch must return plain text content")
                            upsert(state, source_item(f"drive:{file_id}", title, content, url))
                            fetched.add(f"drive:{file_id}")
                        token = listing.get("next_page_token")
                        if not token:
                            break
                        if token in seen or len(seen) >= 100:
                            raise ValueError("Drive pagination did not terminate")
                        seen.add(token)
                    for item in state["items"].values():
                        if item["source"].startswith("drive:") and item["source"] not in fetched:
                            item.update(status="unavailable", approved_revision="")
                    state["drive_status"] = "Connected; refreshed RFC documents"
                except Exception as exc:
                    state["drive_status"] = f"Refresh failed: {exc}"
                    # Never execute cached Drive documents after a failed freshness check.
                    for item in state["items"].values():
                        if item["source"].startswith("drive:"):
                            item.update(approved_revision="", status="needs_refresh")
            else:
                state["drive_status"] = "Imported snapshots only; configure Drive MCP tools for recurring refresh"
            self.save(state)
            return self.public(state)

    async def select(self, item_id: str, revision: str, queued: bool):
        async with self.lock:
            state = self.state()
            item = state["items"].get(item_id)
            if not item or item["revision"] != revision or item["status"] in {"unavailable", "needs_refresh", "running"}:
                raise ValueError("RFC changed or is unavailable; scan and select its current revision")
            if queued and any(other["id"] != item_id and other["revision"] == revision and other["status"] in {"queued", "running"} for other in state["items"].values()):
                raise ValueError("This RFC content is already queued from another source")
            item.update(approved_revision=revision if queued else "", status="queued" if queued else "available")
            self.save(state)
            return self.public(state)

    def claim(self):
        path = root() / "lease.json"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            lease = read_json(path, {})
            try:
                process = psutil.Process(lease["pid"])
                if abs(process.create_time() - lease["created"]) < 1:
                    raise ValueError("Another ANZU scheduler owns the development lease")
            except (psutil.NoSuchProcess, KeyError):
                pass
            path.unlink(missing_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "created": psutil.Process().create_time()}, stream)
        self.lease = path

    def release(self):
        if self.lease:
            self.lease.unlink(missing_ok=True)
            self.lease = None

    async def launch(self):
        async with self.lock:
            state = self.state()
            if kill_switch_active():
                raise ValueError("Emergency stop is active")
            if any(run["status"] == "running" for run in state["runs"]):
                raise ValueError("A development mission is already running")
            config = DevelopmentConfig.model_validate(state["config"])
            if config.resource_hold:
                raise ValueError(f"Local workers reserved: {config.resource_hold}")
            if state["failures"] >= config.failure_limit:
                raise ValueError("Failure limit reached; inspect results and save settings to resume")
            ordered = self.ordered_items(state)
            item = next((i for i in ordered if i.get("source") != "owner_task" and i["status"] == "queued" and i["approved_revision"] == i["revision"]
                         and all(state["items"].get(dep, {}).get("status") == "completed" for dep in i.get("dependencies", []))), None)
            if not item:
                return self.public(state)
            await model_capabilities(config)
            self.claim()
            run_id = uuid.uuid4().hex
            control = root() / run_id
            try:
                spec = await asyncio.to_thread(create_worktree, config.repo or repo_root(), branch=f"jarvis/self-dev-{run_id[:12]}", ref=config.base_ref)
                # Recheck repository content against the exact selected base SHA.
                if item["path"]:
                    text = (await asyncio.to_thread(run_git, spec.path, ["show", f"{spec.start_commit}:{item['path']}"])).stdout
                    if hashlib.sha256(text.encode()).hexdigest() != item["revision"]:
                        item.update(status="available", approved_revision="")
                        raise ValueError("RFC revision changed before launch; rescan and queue it again")
                control.mkdir(parents=True)
                settings = load_settings().model_dump()
                settings["inference"].update(backend="ollama", host=httpx.URL(config.ollama_url).host, port=int(httpx.URL(config.ollama_url).port or 80), remote_model=config.coder_model, profile="balanced", auto_load=False, vision=False)
                settings["front_responder"].update(enabled=False, resident=False)
                settings["allowed_directories"] = [spec.path]
                settings["mcp_servers"] = []
                # This mission owns only its Qwen worker. It must not delegate to
                # the owner's active Aider/Antigravity or other external agents.
                settings["disabled_tools"] = sorted(set(settings.get("disabled_tools", [])) | {"code_worker", "self_development", "cua", "ufo", "reflex_computer_use"})
                settings["coding"].update(specialist_model="", local_max_attempts=1)
                settings["self_dev"].update(max_paid_spend_eur=0, max_paid_invocations=0, auto_merge=False)
                settings["auth_token"] = ""
                write_json(control / "data/settings.json", settings)
                permission = data_dir() / "computer-permissions.json"
                if permission.exists():
                    shutil.copy2(permission, control / "data/computer-permissions.json")
                task_id = str(uuid.uuid4())
                write_json(control / "mission.json", {"id": run_id, "task_id": task_id, "item": item, "config": config.model_dump(), "spec": spec.as_dict(), "owner_root": str(repo_root()), "started_at": time.time()})
                env = dict(os.environ, JARVIS_ROOT=str(control), PYTHONPATH=str(Path(__file__).resolve().parents[2]), ANZU_DEVELOPMENT_MISSION=run_id)
                # Load trusted running code, never the candidate checkout's Python modules.
                log = (control / "worker.log").open("w", encoding="utf-8")
                try:
                    command = [sys.executable, "--development-worker", str(control)] if getattr(sys, "frozen", False) else [sys.executable, "-m", "app.agent.development_worker", str(control)]
                    process = subprocess.Popen(command, cwd=str(control), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                finally:
                    log.close()
                self.process = process
                run = {"id": run_id, "task_id": task_id, "item_id": item["id"], "title": item["title"], "revision": item["revision"], "status": "running", "started_at": time.time(), "worktree_id": spec.id, "pid": process.pid, "created": psutil.Process(process.pid).create_time(), "worktree": spec.path, "base_sha": spec.start_commit, "branch": spec.branch}
                state["runs"].append(run)
                item["status"] = "running"
                self.save(state)
                return self.public(state)
            except Exception:
                self.save(state)
                self.release()
                raise

    def owned_process(self, run):
        try:
            proc = psutil.Process(run["pid"])
            if abs(proc.create_time() - run["created"]) < 1 and any(marker in proc.cmdline() for marker in ("app.agent.development_worker", "--development-worker")) and str(root() / run["id"]) in proc.cmdline():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
            pass
        return None

    def stop_process(self, run):
        proc = self.owned_process(run)
        if proc:
            for child in proc.children(recursive=True):
                child.terminate()
            proc.terminate()
            try:
                proc.wait(5)
            except psutil.TimeoutExpired:
                proc.kill()

    async def stop(self):
        async with self.lock:
            state = self.state()
            state["config"]["enabled"] = False
            state["config"]["away_mode"] = False
            for run in state["runs"]:
                if run["status"] == "running":
                    await asyncio.to_thread(self.stop_process, run)
                    run.update(status="stopped", ended_at=time.time())
                    state["items"][run["item_id"]].update(status="stopped", approved_revision="")
            self.save(state)
            self.release()
            return self.public(state)

    async def command(self, run_id: str, task_id: str, expected_payload: str, approved: bool):
        async with self.lock:
            state = self.state()
            run = next((r for r in state["runs"] if r["id"] == run_id and r["task_id"] == task_id and r["status"] == "running"), None)
            if not run:
                raise ValueError("Mission is not active")
            status = read_json(root() / run_id / "status.json", {})
            if not status.get("waiting_for_confirmation") or status.get("confirmation_payload") != expected_payload:
                raise ValueError("Pending action changed; refresh before deciding")
            write_json(root() / run_id / "command.json", {"task_id": task_id, "approved": approved, "expected_payload": expected_payload})
            return {"queued": True}

    async def tick(self):
        await self.dispatch_owner()
        from .development_publication import deliver
        if self.publication is None or self.publication.done():
            state = self.state()
            if state["config"].get("away_mode") and not state["config"].get("resource_hold") and not kill_switch_active():
                ready = next((r for r in state["runs"] if r["status"] in {"review_ready", "build_pending"}), None)
                if ready:
                    self.publication = asyncio.create_task(deliver(self, ready["id"]))
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            for run in state["runs"]:
                if run["status"] != "running":
                    continue
                control = root() / run["id"]
                result = read_json(control / "result.json", None)
                expired = time.time() - run["started_at"] >= config.max_run_minutes * 60
                alive = self.owned_process(run)
                if result is None and alive and not expired and not kill_switch_active():
                    return
                if alive:
                    await asyncio.to_thread(self.stop_process, run)
                if self.process:
                    self.process.poll()
                status = result.get("status", "failed") if result else ("timed_out" if expired else "interrupted")
                run.update(status=status, ended_at=time.time(), result=result or {"error": "Worker stopped without a verified result"})
                state["failures"] = 0 if status == "review_ready" else state["failures"] + 1
                item = state["items"][run["item_id"]]
                if item["revision"] == run["revision"]:
                    item.update(status=status, approved_revision="")
                self.release()
                self.save(state)
            due = config.enabled and not (self.publication and not self.publication.done()) and not config.resource_hold and time.time() >= state["next_run"] and state["failures"] < config.failure_limit and not kill_switch_active()
            if due:
                state["next_run"] = time.time() + config.interval_minutes * 60
                self.save(state)
        if due:
            await self.scan()
            if config.away_mode:
                async with self.lock:
                    state = self.state()
                    for item in self.ordered_items(state):
                        if item.get("source", "").startswith("repo:") and item["status"] == "available":
                            item.update(status="queued", approved_revision=item["revision"])
                    self.save(state)
            await self.launch()

    async def loop(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                async with self.lock:
                    state = self.state()
                    state["error"] = str(exc)
                    self.save(state)
            await asyncio.sleep(5)

    async def start(self):
        if self.runner is None:
            # Adopt a surviving worker's lease; do not replay an interrupted task.
            state = self.state()
            if any(r["status"] == "running" and self.owned_process(r) for r in state["runs"]):
                self.claim()
            self.runner = asyncio.create_task(self.loop())

    async def close(self):
        if self.runner:
            self.runner.cancel()
            try:
                await self.runner
            except asyncio.CancelledError:
                pass
            self.runner = None
        # Preserve scheduling preference across clean app restarts. Active edits
        # are interrupted and remain reviewable; they are never replayed.
        enabled = self.state()["config"]["enabled"]
        away_mode = self.state()["config"].get("away_mode", False)
        await self.stop()
        async with self.lock:
            state = self.state()
            state["config"]["enabled"] = enabled
            state["config"]["away_mode"] = away_mode
            self.save(state)


DEVELOPMENT = DevelopmentScheduler()
