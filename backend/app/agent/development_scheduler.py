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
from . import development_build as builds
from . import development_publish as publish
from . import development_queue as queue
from . import development_review as review
from .self_dev import kill_switch_active
from .worktrees import WorktreeSpec, create_worktree, run_git

AWAY_EXPLANATION = ("ANZU will work through the backlog, merge verified improvements into development, "
                    "and prepare new builds while you are away.")
# Delivery stages that occupy the single development slot.
ACTIVE_STAGES = {"implementing", "repairing", "testing", "reviewing", "publishing", "waiting_ci", "merging", "merged"}
PHASES = {"implementing": "working", "repairing": "working", "testing": "testing", "reviewing": "reviewing",
          "publishing": "testing", "waiting_ci": "testing", "merging": "building", "merged": "building"}


class DevelopmentConfig(BaseModel):
    enabled: bool = False
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
    # Independent review model; empty uses the coder model in a fresh context.
    review_model: str = ""
    max_repairs: int = Field(default=2, ge=0, le=5)
    ci_timeout_minutes: int = Field(default=120, ge=5, le=1440)

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
    return {"config": DevelopmentConfig().model_dump(), "items": {}, "runs": [], "next_run": 0, "failures": 0, "error": "", "drive_status": "Not connected",
            "order": [], "pins": [], "queue_revision": 0, "queue_history": [], "deliveries": {}, "builds": {},
            "away": {"enabled": False, "activated_at": 0, "activated_by": "", "explained": False, "summary": None, "last_scan": 0},
            "evidence": {"checked_at": 0, "error": "", "merged": {}, "open": {}}}


def with_defaults(state):
    """Older state files gain the RFC-0211 queue/Away Mode keys without losing data."""
    for key, value in default_state().items():
        state.setdefault(key, value)
    for key, value in default_state()["away"].items():
        state["away"].setdefault(key, value)
    return state


def models_held_unloaded() -> bool:
    """The owner's manual unload guard (#690): background work must not load models.

    Same bridge as ``model_launch.idle_keep_alive``: builds without the #690 guard have
    no manual-unload flag, so nothing is held.
    """
    try:
        from ..inference.idle_unload import warm_blocked
    except ImportError:
        return False
    return warm_blocked()


def ollama_keep_alive() -> str:
    """Every scheduler/worker Ollama request uses the shared idle keep-alive helper."""
    from ..inference.model_launch import idle_keep_alive
    return idle_keep_alive()


MODEL_POLICY = "model_policy.json"


def model_policy() -> dict[str, Any]:
    """What a running mission may send to Ollama right now, resolved in the owner's process.

    Workers run under their control directory with a frozen settings copy, so they never
    resolve keep_alive or the manual-unload guard themselves: the scheduler publishes both
    here on launch and on every tick.
    """
    return {"keep_alive": ollama_keep_alive(), "held": models_held_unloaded(), "updated_at": time.time()}


def publish_model_policy(control: Path, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or model_policy()
    write_json(control / MODEL_POLICY, policy)
    return policy


def source_item(source: str, title: str, content: str, url: str = "", path: str = "", *, kind: str = "", meta: dict[str, Any] | None = None):
    if not content.strip() or len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("RFC must contain text and fit within 1 MB")
    kind = kind or source.split(":", 1)[0]
    metadata = queue.ticket_metadata(title, content, path=path)
    metadata.update(meta or {})
    return {"id": hashlib.sha256(source.encode()).hexdigest()[:24], "source": source, "kind": kind, "title": title[:300], "content": content,
            "revision": hashlib.sha256(content.encode()).hexdigest(), "url": url, "path": path, **metadata}


def upsert(state, item):
    old = state["items"].get(item["id"], {})
    same = old.get("revision") == item["revision"]
    # A changed source invalidates pending selection; deliveries notice the new revision and stop.
    status = old.get("status", "available") if same else "available"
    state["items"][item["id"]] = {**old, **item, "approved_revision": old.get("approved_revision", "") if same else "", "status": status,
                                  "created_at": old.get("created_at", time.time()), "updated_at": time.time()}


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
        # Accepts "Status: accepted" and the bold "**Status:** accepted" header forms.
        if re.search(r"(?im)^\W*status\W*:\W*accepted\b", content):
            title = next((line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("# ")), name)
            out.append(source_item(f"repo:{identity}:{name}", title, content, path=name, kind="rfc"))
    plan = run_git(repo, ["show", f"{config.base_ref}:JARVIS_MASTER_PLAN.md"], check=False)
    if plan.returncode == 0:
        for entry in queue.plan_items(plan.stdout):
            out.append(source_item(f"plan:{identity}:{entry['title']}", entry["title"], entry["content"], kind="plan",
                                   meta={"priority": entry["priority"], "plan_status": entry["plan_status"], "acceptance": entry["acceptance"]}))
    return out


def plan_entry(repo: Path, sha: str, title: str) -> str:
    text = run_git(repo, ["show", f"{sha}:JARVIS_MASTER_PLAN.md"], check=False).stdout
    return next((entry["content"] for entry in queue.plan_items(text) if entry["title"] == title), "")


class ModelCheckError(ValueError):
    """Ollama is unreachable or a configured model is missing; the message is safe to show the owner.

    A ``ValueError`` so the scheduler API answers 409 and the chat tool returns a tool error
    instead of an unhandled 500.
    """


async def model_capabilities(config: DevelopmentConfig):
    result = {}
    base = config.ollama_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        for role, model, required in (("coder", config.coder_model, {"tools"}), ("vision", config.vision_model, {"vision", "tools"})):
            try:
                response = await client.post(base + "/api/show", json={"model": model})
            except httpx.HTTPError as exc:
                raise ModelCheckError(
                    f"Ollama at {base} is not reachable ({type(exc).__name__}); start Ollama or fix the Ollama URL"
                ) from exc
            if response.status_code == 404:
                raise ModelCheckError(
                    f"The {role} model {model} is not installed in Ollama at {base}; run `ollama pull {model}` or choose another model"
                )
            if response.is_error:
                raise ModelCheckError(f"Ollama at {base} could not describe the {role} model {model} (HTTP {response.status_code})")
            try:
                capabilities = set(response.json().get("capabilities", []))
            except ValueError as exc:
                raise ModelCheckError(f"Ollama at {base} returned an unreadable answer for the {role} model {model}") from exc
            if not required <= capabilities:
                raise ModelCheckError(f"{role} model {model} lacks {', '.join(sorted(required - capabilities))}")
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
        self.kick = None

    def state(self):
        return with_defaults(read_json(root() / "state.json", default_state()))

    def save(self, state):
        write_json(root() / "state.json", state)

    async def configure(self, config: DevelopmentConfig, *, resume: bool = True):
        """Save the scheduler settings.

        ``resume`` (the owner's explicit save in Self-development) also clears the
        consecutive-failure breaker; chat changes never do.
        """
        async with self.lock:
            state = self.state()
            if any(r["status"] == "running" for r in state["runs"]):
                raise ValueError("Stop the active mission before changing its configuration")
            state["config"] = config.model_dump()
            state["next_run"] = time.time() + config.interval_minutes * 60
            if resume:
                state["failures"] = 0
                state["error"] = ""
            self.save(state)
            return self.public(state)

    # ----- views -------------------------------------------------------------------------

    def active_delivery(self, state):
        return next((d for d in state["deliveries"].values() if d["stage"] in ACTIVE_STAGES), None)

    def publish_authorized(self, state, delivery) -> bool:
        """Push/PR/merge only for the owner's Publish, or an Away Mode task while Away Mode is on.

        Manual, scheduled and chat launches keep the owner-requested policy: they stop at
        "approved" and wait for the Publish button. Turning Away Mode off revokes it.
        """
        if kill_switch_active():
            return False
        if delivery.get("authorized_by") == "owner":
            return True
        return delivery.get("authorized_by") == "away" and bool(state["away"]["enabled"])

    def gates(self, state, config: DevelopmentConfig) -> str:
        """Why autonomous development cannot dispatch now ("" when it can)."""
        from ..engine_mode import model_enabled
        if kill_switch_active():
            return "Emergency stop is active"
        if state["failures"] >= config.failure_limit:
            return f"Paused after {state['failures']} consecutive failures; review them and save settings to resume"
        if config.resource_hold:
            return f"Waiting for priority work: {config.resource_hold}"
        if not model_enabled(load_settings()):
            return "Local models are switched off in Engine mode"
        if models_held_unloaded():
            return "You unloaded the models; development resumes after your next turn or an explicit Load"
        if state["evidence"].get("error"):
            return state["evidence"]["error"]
        return ""

    def phase(self, state) -> dict[str, str]:
        config = DevelopmentConfig.model_validate(state["config"])
        away = state["away"]
        active = self.active_delivery(state)
        if not away["enabled"]:
            return {"phase": "paused", "detail": "Away Mode is off"}
        gate = self.gates(state, config)
        if gate:
            return {"phase": "waiting for priority work" if config.resource_hold and not kill_switch_active() else "needs attention", "detail": gate}
        if active:
            return {"phase": PHASES[active["stage"]], "detail": active.get("waiting") or f"{active['title']}: {active['stage'].replace('_', ' ')}"}
        if any(r["status"] == "running" for r in state["runs"]):
            return {"phase": "working", "detail": "Mission running"}
        return {"phase": "idle", "detail": away.get("waiting") or "Looking for the next eligible task"}

    def queue_view(self, state):
        automatic = state["away"]["enabled"]
        chosen, reasons = queue.next_eligible(state, automatic=automatic)
        by_id = {r["id"]: r["reason"] for r in reasons}
        pins = set(state["pins"])
        upcoming = []
        for item_id in state["order"]:
            item = state["items"].get(item_id)
            if not item:
                continue
            upcoming.append({"id": item_id, "title": item["title"], "kind": item.get("kind", ""), "status": item["status"],
                             "priority": item.get("priority", 3), "depends": item.get("depends", []), "pinned": item_id in pins,
                             "reason": by_id.get(item_id, ""), "next": bool(chosen and chosen["id"] == item_id),
                             "revision": item["revision"]})
        active = self.active_delivery(state)
        running = next((r for r in state["runs"] if r["status"] == "running"), None)
        titles = {i: state["items"][i]["title"] for i in state["items"]}
        history = [{**{k: v for k, v in h.items() if k not in {"before", "after"}},
                    "order": [titles.get(i, i) for i in h["after"][:10]]} for h in state["queue_history"][-10:]]
        return {"revision": state["queue_revision"], "automatic": automatic, "upcoming": upcoming,
                "next_eligible": chosen["id"] if chosen else "",
                "active": ({"id": active["id"], "title": active["title"], "stage": active["stage"], "kind": "development"} if active
                           else {"id": running["id"], "title": running["title"], "stage": "implementing", "kind": "development"} if running else None),
                "history": history}

    def public(self, state=None):
        state = state or self.state()
        runs = []
        for run in state["runs"][-30:]:
            view = dict(run)
            status = read_json(root() / run["id"] / "status.json", {})
            view["task"] = status
            runs.append(view)
        deliveries = sorted(state["deliveries"].values(), key=lambda d: d["started_at"])[-30:]
        return {**state, "items": [{k: v for k, v in item.items() if k != "content"} for item in state["items"].values()], "runs": runs,
                "emergency_stop": kill_switch_active(), "deliveries": deliveries, "builds": list(state["builds"].values()),
                "queue": self.queue_view(state), "status": self.phase(state)}

    # ----- intake --------------------------------------------------------------------------

    def map_drive(self, state):
        """A Drive RFC maps to a repository RFC by number; unmapped Drive work stays blocked."""
        repo_numbers = {i["rfc"] for i in state["items"].values() if i.get("kind") == "rfc" and i.get("rfc")}
        for item in state["items"].values():
            if item.get("kind") == "drive":
                item["maps_to"] = f"RFC-{item['rfc']}" if item.get("rfc") in repo_numbers else ""

    async def import_drive(self, file_id: str, title: str, content: str):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", file_id):
            raise ValueError("Invalid Drive file identity")
        async with self.lock:
            state = self.state()
            upsert(state, source_item(f"drive:{file_id}", title, content, f"https://drive.google.com/file/d/{file_id}/view"))
            self.map_drive(state)
            queue.replan(state)
            self.save(state)
            return self.public(state)

    async def scan(self):
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            items = await asyncio.to_thread(repo_items, config)
            found = {item["id"] for item in items}
            for old in state["items"].values():
                if old["source"].startswith(("repo:", "plan:")) and old["id"] not in found and old["status"] not in queue.ACTIVE_STATUSES:
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
            self.map_drive(state)
            queue.replan(state)
            state["away"]["last_scan"] = time.time()
            self.save(state)
            return self.public(state)

    async def select(self, item_id: str, revision: str, queued: bool):
        async with self.lock:
            state = self.state()
            item = state["items"].get(item_id)
            if not item or item["revision"] != revision or item["status"] in {"unavailable", "needs_refresh"} | queue.ACTIVE_STATUSES | queue.MERGED_STATUSES | queue.DONE_STATUSES:
                raise ValueError("RFC changed or is unavailable; scan and select its current revision")
            if queued and any(other["id"] != item_id and other["revision"] == revision and other["status"] in {"queued"} | queue.ACTIVE_STATUSES for other in state["items"].values()):
                raise ValueError("This RFC content is already queued from another source")
            item.update(approved_revision=revision if queued else "", status="queued" if queued else "available", approved_by="owner" if queued else "")
            queue.replan(state)
            self.save(state)
            return self.public(state)

    # ----- upcoming list ------------------------------------------------------------------

    async def reorder(self, order: list[str], *, expected_revision: int, actor: str, reason: str = ""):
        async with self.lock:
            state = self.state()
            result = queue.reorder(state, order, expected_revision=expected_revision, actor=actor, reason=reason)
            self.save(state)
            return {**result, "queue": self.queue_view(state)}

    async def move(self, item_id: str, *, expected_revision: int, actor: str, reason: str = "", to: int | None = None, delta: int = 0):
        async with self.lock:
            state = self.state()
            result = queue.move(state, item_id, to=to, delta=delta, expected_revision=expected_revision, actor=actor, reason=reason)
            self.save(state)
            return {**result, "queue": self.queue_view(state)}

    async def release_pin(self, item_id: str, *, expected_revision: int):
        async with self.lock:
            state = self.state()
            result = queue.release_pin(state, item_id, expected_revision=expected_revision)
            self.save(state)
            return {**result, "queue": self.queue_view(state)}

    async def undo(self, history_id: str, *, expected_revision: int, actor: str):
        async with self.lock:
            state = self.state()
            result = queue.undo(state, history_id, expected_revision=expected_revision, actor=actor)
            self.save(state)
            return {**result, "queue": self.queue_view(state)}

    # ----- missions ------------------------------------------------------------------------

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
            config = DevelopmentConfig.model_validate(state["config"])
            item, _ = queue.next_eligible(state, automatic=False)
            if not item:
                # Preserve the slot rules even when nothing is queued.
                self.check_slot(state, config)
                return self.public(state)
            # Not a publish authorization: the result waits at "approved" for the owner's Publish.
            await self.launch_mission(state, config, item, authorized_by="")
            return self.public(state)

    def check_slot(self, state, config: DevelopmentConfig):
        if kill_switch_active():
            raise ValueError("Emergency stop is active")
        if any(run["status"] == "running" for run in state["runs"]):
            raise ValueError("A development mission is already running")
        if config.resource_hold:
            raise ValueError(f"Local workers reserved: {config.resource_hold}")
        if state["failures"] >= config.failure_limit:
            raise ValueError("Failure limit reached; inspect results and save settings to resume")

    async def launch_mission(self, state, config: DevelopmentConfig, item, *, authorized_by: str, delivery=None, findings: str = ""):
        """Start one isolated worker for ``item`` (caller holds ``self.lock``).

        Without ``delivery`` a new delivery and worktree pinned to the base revision are
        created; with it, a repair mission continues in the delivery's worktree.
        """
        from ..engine_mode import model_enabled
        self.check_slot(state, config)
        active = self.active_delivery(state)
        if active and (delivery is None or active["id"] != delivery["id"]):
            raise ValueError(f"{active['title']} is still being {active['stage'].replace('_', ' ')}; one development task runs at a time")
        if not model_enabled(load_settings()):
            raise ValueError("Local models are switched off in Engine mode")
        if models_held_unloaded():
            raise ValueError("You unloaded the models; development waits for your next turn or an explicit Load")
        await model_capabilities(config)
        self.claim()
        run_id = uuid.uuid4().hex
        control = root() / run_id
        try:
            if delivery is None:
                spec = await asyncio.to_thread(create_worktree, config.repo or repo_root(), branch=f"{publish.SELF_DEV_BRANCH_PREFIX}{run_id[:12]}", ref=config.base_ref)
                # Recheck the ticket against the exact selected base SHA.
                if item.get("kind") == "plan":
                    current = await asyncio.to_thread(plan_entry, Path(spec.path), spec.start_commit, item["title"])
                    if hashlib.sha256(current.encode()).hexdigest() != item["revision"]:
                        item.update(status="available", approved_revision="")
                        raise ValueError("Plan entry changed before launch; rescan and queue it again")
                elif item["path"]:
                    text = (await asyncio.to_thread(run_git, spec.path, ["show", f"{spec.start_commit}:{item['path']}"])).stdout
                    if hashlib.sha256(text.encode()).hexdigest() != item["revision"]:
                        item.update(status="available", approved_revision="")
                        raise ValueError("RFC revision changed before launch; rescan and queue it again")
                try:
                    _, north_star_blob = await asyncio.to_thread(review.north_star_at, spec.path, spec.start_commit)
                except review.ReviewError as exc:
                    raise ValueError(str(exc)) from exc
                delivery = {"id": run_id, "item_id": item["id"], "revision": item["revision"], "title": item["title"], "kind": item.get("kind", ""),
                            "spec": spec.as_dict(), "worktree": spec.path, "branch": spec.branch, "base_sha": spec.start_commit,
                            "base_ref": config.base_ref, "north_star_blob": north_star_blob, "stage": "implementing", "head_sha": "",
                            "tests": None, "review": None, "repairs": 0, "pr": None, "merge_sha": "", "history": [], "error": "",
                            "authorized_by": authorized_by if authorized_by in {"owner", "away"} else "", "started_at": time.time(), "base_changes": 0}
                state["deliveries"][delivery["id"]] = delivery
                stage = "implementing"
            else:
                spec = WorktreeSpec(**{**delivery["spec"], "start_commit": delivery["base_sha"]})
                stage = "repairing"
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
            write_json(control / "mission.json", {"id": run_id, "task_id": task_id, "item": item, "config": config.model_dump(), "spec": spec.as_dict(),
                                                  "owner_root": str(repo_root()), "started_at": time.time(), "delivery_id": delivery["id"],
                                                  "north_star_blob": delivery["north_star_blob"], "findings": findings})
            publish_model_policy(control)
            env = dict(os.environ, JARVIS_ROOT=str(control), PYTHONPATH=str(Path(__file__).resolve().parents[2]), ANZU_DEVELOPMENT_MISSION=run_id)
            # Load trusted running code, never the candidate checkout's Python modules.
            log = (control / "worker.log").open("w", encoding="utf-8")
            try:
                command = [sys.executable, "--development-worker", str(control)] if getattr(sys, "frozen", False) else [sys.executable, "-m", "app.agent.development_worker", str(control)]
                process = spawn_worker(command, cwd=str(control), env=env, stdout=log)
            finally:
                log.close()
            self.process = process
            run = {"id": run_id, "task_id": task_id, "item_id": item["id"], "title": item["title"], "revision": item["revision"], "status": "running", "started_at": time.time(), "pid": process.pid, "created": psutil.Process(process.pid).create_time(), "worktree": spec.path, "base_sha": spec.start_commit, "branch": spec.branch, "delivery_id": delivery["id"]}
            state["runs"].append(run)
            item["status"] = "running"
            self.set_stage(state, delivery, stage, findings[:2000] if findings else "Mission started")
            self.save(state)
        except Exception:
            if delivery is not None and delivery["stage"] == "implementing" and not any(r.get("delivery_id") == delivery["id"] for r in state["runs"]):
                state["deliveries"].pop(delivery["id"], None)
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

    async def halt(self, state, reason: str):
        """Stop the running mission safely: terminate the worker, then checkpoint its edits."""
        for run in state["runs"]:
            if run["status"] != "running":
                continue
            await asyncio.to_thread(self.stop_process, run)
            run.update(status="stopped", ended_at=time.time())
            item = state["items"].get(run["item_id"])
            if item:
                item.update(status="stopped", approved_revision="", attempted_revision=run["revision"])
            delivery = state["deliveries"].get(run.get("delivery_id", ""))
            if delivery and Path(delivery["worktree"]).exists():
                try:
                    sha = await asyncio.to_thread(publish.checkpoint, delivery["worktree"], f"ANZU checkpoint: {reason}")
                    delivery["checkpoint_sha"] = sha
                except subprocess.CalledProcessError as exc:
                    delivery["error"] = f"Checkpoint failed: {(exc.stderr or exc.stdout or '').strip()[:300]}"
            if delivery:
                self.set_stage(state, delivery, "stopped", reason)
        self.release()

    async def stop(self):
        async with self.lock:
            state = self.state()
            state["config"]["enabled"] = False
            if state["away"]["enabled"]:
                self.end_away(state, "Stopped by the owner")
            await self.halt(state, "stopped by the owner")
            self.save(state)
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

    # ----- delivery pipeline ----------------------------------------------------------------

    def set_stage(self, state, delivery, stage: str, detail: str = ""):
        delivery["stage"] = stage
        delivery["updated_at"] = time.time()
        delivery.pop("waiting", None)
        delivery["history"] = (delivery.get("history", []) + [{"stage": stage, "at": time.time(), "detail": detail[:2000]}])[-40:]
        item = state["items"].get(delivery["item_id"])
        if item and item["revision"] == delivery["revision"]:
            mapped = {"implementing": "running", "repairing": "running", "stopped": "stopped"}.get(stage, stage)
            item["status"] = mapped
            if stage in {"needs_attention", "stopped"}:
                item.update(approved_revision="", attempted_revision=delivery["revision"])
        if stage in {"delivered", "build_failed", "needs_attention", "stopped"}:
            delivery["ended_at"] = time.time()
        queue.replan(state)

    def attention(self, state, delivery, reason: str):
        delivery["error"] = reason[:4000]
        state["failures"] += 1
        self.set_stage(state, delivery, "needs_attention", reason)

    async def repair_or_attention(self, state, config: DevelopmentConfig, delivery, findings: str):
        if delivery["repairs"] >= config.max_repairs:
            self.attention(state, delivery, f"Repair limit reached. {findings}")
            return
        item = state["items"].get(delivery["item_id"])
        delivery["repairs"] += 1
        try:
            await self.launch_mission(state, config, item, authorized_by=delivery.get("authorized_by", ""), delivery=delivery, findings=findings)
        except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            self.attention(state, delivery, f"Repair could not start: {exc}. {findings}")

    def pipeline_next(self, state):
        active = self.active_delivery(state)
        if active and active["stage"] not in {"implementing", "repairing"}:
            return active
        if active:
            return None
        return next((d for d in sorted(state["deliveries"].values(), key=lambda d: d["started_at"])
                     if d["stage"] == "approved" and self.publish_authorized(state, d)), None)

    async def advance(self, delivery_id: str):
        """Run one bounded pipeline step outside the state lock, then apply it if still current."""
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            delivery = state["deliveries"].get(delivery_id)
            if not delivery or kill_switch_active():
                return
            item = state["items"].get(delivery["item_id"])
            if delivery["stage"] in {"testing", "reviewing", "approved", "publishing", "waiting_ci"} and (not item or item["revision"] != delivery["revision"]):
                self.attention(state, delivery, "The ticket source changed during delivery; its new revision is evaluated as a new task")
                self.save(state)
                return
            stage = delivery["stage"]
            snapshot = json.loads(json.dumps(delivery))
            authorized = self.publish_authorized(state, delivery)
            job = dict(state["builds"].get(delivery.get("merge_sha", ""), {}))
            ticket = item["content"] if item else ""
        try:
            if stage == "testing":
                update = await self.step_test(snapshot, config)
            elif stage == "reviewing":
                update = await self.step_review(snapshot, config, ticket)
            elif stage == "approved":
                update = {"stage": "publishing", "detail": "Publication authorized"} if authorized else None
            elif stage == "publishing":
                update = await self.step_publish(snapshot) if authorized else None
            elif stage == "waiting_ci":
                update = await self.step_ci(snapshot, config)
            elif stage == "merging":
                update = await self.step_merge(snapshot) if authorized else None
            elif stage == "merged":
                update = await self.step_build(snapshot, config, job, authorized)
            else:
                update = None
        except publish.BaseConflict as exc:
            update = {"repair": f"Merge development into your branch and resolve the conflict: {exc}"}
        except (publish.PublishError, review.ReviewError, builds.BuildUnavailable, subprocess.CalledProcessError, OSError) as exc:
            detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
            update = {"attention": f"{stage.replace('_', ' ').capitalize()} failed: {detail}"[:4000]}
        if update is None:
            return
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            delivery = state["deliveries"].get(delivery_id)
            if not delivery or delivery["stage"] != stage:
                return
            if "attention" in update:
                self.attention(state, delivery, update["attention"])
            elif "repair" in update:
                delivery.update(update.get("set", {}))
                await self.repair_or_attention(state, config, delivery, update["repair"])
            else:
                delivery.update(update.get("set", {}))
                if "build" in update:
                    state["builds"][delivery["merge_sha"]] = update["build"]
                    if update["build"]["status"] == "succeeded":
                        state["failures"] = 0
                        self.set_stage(state, delivery, "delivered", f"Build ready: {update['build']['artifact']}")
                    elif update["build"]["status"] == "failed":
                        self.set_stage(state, delivery, "build_failed", update["build"]["error"])
                elif update.get("stage"):
                    if update["stage"] == "merged":
                        state["builds"].setdefault(delivery["merge_sha"], builds.new_job(delivery["merge_sha"], delivery["item_id"], delivery["pr"]))
                    self.set_stage(state, delivery, update["stage"], update.get("detail", ""))
            self.save(state)

    async def step_test(self, d, config: DevelopmentConfig):
        from .development_worker import verification
        head = await asyncio.to_thread(publish.commit_candidate, d["worktree"], f"{d['title']} (ANZU self-development)",
                                       exclude=[f"docs/rfcs/external-{d['item_id']}.md"])
        control = root() / d["id"]
        control.mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(verification, d["worktree"], control, config.max_run_minutes * 60, d["base_sha"])
        tests = {"head_sha": head, "ok": bool(result["ok"]), "error": result.get("error", ""), "at": time.time(),
                 "checks": [{"command": c["command"], "returncode": c["returncode"], "duration_seconds": c.get("duration_seconds"),
                             "output": c["output"][-4000:]} for c in result.get("checks", [])]}
        if tests["ok"]:
            return {"set": {"head_sha": head, "tests": tests, "review": None}, "stage": "reviewing", "detail": f"Checks passed at {head[:12]}"}
        failing = [f"$ {' '.join(map(str, c['command']))} (exit {c['returncode']})\n{c['output'][-3000:]}" for c in tests["checks"] if c["returncode"] != 0]
        return {"set": {"head_sha": head, "tests": tests}, "repair": "Trusted verification failed. " + (tests["error"] or "\n\n".join(failing))}

    async def step_review(self, d, config: DevelopmentConfig, ticket: str):
        from ..engine_mode import model_enabled
        if models_held_unloaded() or not model_enabled(load_settings()):
            return {"set": {"waiting": "Review waits until local models may load again"}}
        head = (await asyncio.to_thread(run_git, d["worktree"], ["rev-parse", "HEAD"])).stdout.strip()
        if not d.get("tests") or head != d["tests"]["head_sha"]:
            return {"set": {"tests": None, "review": None}, "stage": "testing", "detail": "Head changed after testing; testing again"}
        north_star, blob = await asyncio.to_thread(review.north_star_at, d["worktree"], d["base_sha"])
        record = await review.review_candidate(worktree=d["worktree"], base_sha=d["base_sha"], head_sha=head, ticket=ticket,
                                               north_star=north_star, evidence=d["tests"], ollama_url=config.ollama_url,
                                               model=config.review_model or config.coder_model, keep_alive=ollama_keep_alive())
        record["north_star_blob"] = blob
        record["at"] = time.time()
        if record["approved"]:
            return {"set": {"review": record}, "stage": "approved", "detail": f"Independent review approved {head[:12]}"}
        findings = "\n".join(f"- [{f['severity']}] {f['file']}: {f['issue']}" for f in record["findings"]) or "- Reviewer did not approve"
        return {"set": {"review": record}, "repair": "Independent review findings to fix:\n" + findings}

    async def step_publish(self, d):
        tip = await asyncio.to_thread(publish.origin_tip, d["worktree"], d["base_ref"])
        if tip != d["base_sha"]:
            contained = (await asyncio.to_thread(run_git, d["worktree"], ["merge-base", "--is-ancestor", tip, "HEAD"], False)).returncode == 0
            if not contained:
                await asyncio.to_thread(publish.merge_base_into, d["worktree"], tip)
            # A moved base invalidates approval: test and review the merged result again.
            return {"set": {"base_sha": tip, "tests": None, "review": None, "base_changes": d.get("base_changes", 0) + 1},
                    "stage": "testing", "detail": f"development moved to {tip[:12]}; validating again"}
        await asyncio.to_thread(publish.push_branch, d["worktree"], d["branch"])
        body = pr_body(d)
        number = await asyncio.to_thread(publish.ensure_pr, d["worktree"], branch=d["branch"], base=d["base_ref"],
                                         title=f"{d['title'][:200]} (ANZU self-development)", body=body)
        return {"set": {"pr": number, "ci_started_at": time.time()}, "stage": "waiting_ci", "detail": f"PR #{number} opened at {d['review']['head_sha'][:12]}"}

    async def step_ci(self, d, config: DevelopmentConfig):
        outcome = await asyncio.to_thread(publish.check_outcome, d["worktree"], d["pr"], d["review"]["head_sha"])
        if outcome["outcome"] == "pending":
            if time.time() - d.get("ci_started_at", time.time()) > config.ci_timeout_minutes * 60:
                return {"attention": f"CI did not finish within {config.ci_timeout_minutes} minutes on PR #{d['pr']}"}
            return {"set": {"ci": outcome, "waiting": outcome["detail"]}}
        if outcome["outcome"] == "head_changed":
            return {"attention": outcome["detail"] + "; ANZU will not merge a head it did not review"}
        if outcome["outcome"] == "failed":
            return {"set": {"ci": outcome}, "repair": f"CI failed on PR #{d['pr']}: {outcome['detail']}"}
        tip = await asyncio.to_thread(publish.origin_tip, d["worktree"], d["base_ref"])
        if tip != d["base_sha"]:
            return {"set": {"ci": outcome}, "stage": "publishing", "detail": f"development moved to {tip[:12]} during CI"}
        return {"set": {"ci": outcome}, "stage": "merging", "detail": outcome["detail"]}

    async def step_merge(self, d):
        merge_sha = await asyncio.to_thread(publish.merge_pr, d["worktree"], d["pr"], d["review"]["head_sha"])
        return {"set": {"merge_sha": merge_sha, "merged_at": time.time()}, "stage": "merged", "detail": f"PR #{d['pr']} merged as {merge_sha[:12]}"}

    async def step_build(self, d, config: DevelopmentConfig, job, authorized: bool):
        if not job:
            job = builds.new_job(d["merge_sha"], d["item_id"], d["pr"])
        if job["status"] == "running":
            polled = await asyncio.to_thread(builds.poll, job)
            return {"build": polled} if polled != job else None
        if job["status"] != "pending":
            return None
        if config.resource_hold:
            return {"set": {"waiting": f"Build waits for priority work: {config.resource_hold}"}}
        if not (authorized or job.get("requested")):
            return {"set": {"waiting": "Build waits for Away Mode or your Build now"}}
        try:
            started = await asyncio.to_thread(builds.start, config.repo or repo_root(), job)
        except builds.BuildUnavailable as exc:
            return {"build": {**job, "status": "failed", "attempts": job["attempts"] + 1, "error": str(exc), "ended_at": time.time()}}
        return {"build": started}

    async def request_publish(self, delivery_id: str):
        async with self.lock:
            state = self.state()
            delivery = state["deliveries"].get(delivery_id)
            if not delivery or delivery["stage"] != "approved":
                raise ValueError("Only an independently approved change can be published")
            delivery["authorized_by"] = "owner"
            self.save(state)
        self.wake()
        return self.public()

    async def retry_build(self, merge_sha: str):
        async with self.lock:
            state = self.state()
            job = state["builds"].get(merge_sha)
            if not job or job["status"] not in {"failed", "pending"}:
                raise ValueError("Only a failed or waiting build can be started")
            delivery = next((d for d in state["deliveries"].values() if d.get("merge_sha") == merge_sha), None)
            if not delivery:
                raise ValueError("No merged task owns this build")
            state["builds"][merge_sha] = {**job, "status": "pending", "requested": True, "error": ""}
            if delivery["stage"] == "build_failed":
                self.set_stage(state, delivery, "merged", "Build retry requested; the merge is not repeated")
            self.save(state)
        self.wake()
        return self.public()

    # ----- Away Mode ------------------------------------------------------------------------

    def summary(self, state, since: float):
        deliveries = [d for d in state["deliveries"].values() if d["started_at"] >= since]
        built = state["builds"]
        def entry(d):
            job = built.get(d.get("merge_sha", ""), {})
            return {"title": d["title"], "stage": d["stage"], "pr": d.get("pr"), "merge_sha": d.get("merge_sha", ""),
                    "artifact": job.get("artifact", ""), "sha256": job.get("sha256", ""), "error": d.get("error", "") or job.get("error", ""),
                    "tests": [{"command": " ".join(map(str, c["command"])), "returncode": c["returncode"]} for c in (d.get("tests") or {}).get("checks", [])]}
        return {"since": since, "until": time.time(),
                "completed": [entry(d) for d in deliveries if d["stage"] == "delivered"],
                "merged_build_failed": [entry(d) for d in deliveries if d["stage"] in {"build_failed", "merged"}],
                "blocked": [entry(d) for d in deliveries if d["stage"] in {"needs_attention", "stopped"}],
                "in_progress": [entry(d) for d in deliveries if d["stage"] in ACTIVE_STAGES - {"merged"} | {"approved"}],
                "merged_prs": sorted(d["pr"] for d in deliveries if d.get("merge_sha"))}

    def end_away(self, state, reason: str):
        from .proactivity import set_away_mode
        away = state["away"]
        away["summary"] = {**self.summary(state, away.get("activated_at", 0)), "reason": reason}
        away["enabled"] = False
        away["waiting"] = ""
        set_away_mode(enabled=False)

    async def set_away(self, enabled: bool, *, actor: str, reason: str = ""):
        """One switch for Away Mode — develop ANZU. Returns the public state plus the
        first-activation explanation."""
        from .proactivity import set_away_mode
        async with self.lock:
            state = self.state()
            explanation = ""
            if enabled:
                if kill_switch_active():
                    raise ValueError("Emergency stop is active; resume ANZU before enabling Away Mode")
                if not state["away"]["enabled"]:
                    if not state["away"]["explained"]:
                        explanation = AWAY_EXPLANATION
                    state["away"].update(enabled=True, activated_at=time.time(), activated_by=actor, explained=True,
                                         summary=None, last_scan=0, waiting="")
                    state["evidence"]["checked_at"] = 0
                    state["evidence"]["error"] = ""
                    state["failures"] = 0
                    set_away_mode(enabled=True, message="Developing ANZU")
            elif state["away"]["enabled"]:
                # Returning stops new missions and publication; in-flight edits are checkpointed.
                self.end_away(state, reason or "Owner returned")
                await self.halt(state, "owner returned")
            self.save(state)
        if enabled:
            self.wake()
        return {**self.public(), "explanation": explanation}

    def wake(self):
        """Dispatch immediately instead of waiting for the next loop tick."""
        if self.runner is not None and (self.kick is None or self.kick.done()):
            self.kick = asyncio.create_task(self.guarded_tick())

    async def refresh_evidence(self, config: DevelopmentConfig):
        try:
            evidence = await asyncio.to_thread(publish.pr_evidence, config.repo or repo_root())
            evidence.update(checked_at=time.time(), error="")
        except publish.PublishError as exc:
            evidence = {"checked_at": time.time(), "error": f"Cannot check delivered and claimed work: {exc}", "merged": {}, "open": {}}
        async with self.lock:
            state = self.state()
            state["evidence"] = evidence
            self.save(state)
        return not evidence["error"]

    async def away_dispatch(self):
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            if not state["away"]["enabled"] or self.active_delivery(state) or any(r["status"] == "running" for r in state["runs"]):
                return
            if any(d["stage"] == "approved" for d in state["deliveries"].values()):
                return
            evidence_stale = time.time() - state["evidence"].get("checked_at", 0) > 300
            scan_stale = time.time() - state["away"].get("last_scan", 0) > config.interval_minutes * 60
            state["evidence"]["error"] = state["evidence"]["error"] if not evidence_stale else ""
            gate = self.gates(state, config)
            if gate:
                return
        if evidence_stale and not await self.refresh_evidence(config):
            return
        if scan_stale:
            await self.scan()
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            if not state["away"]["enabled"] or self.gates(state, config) or self.active_delivery(state):
                return
            queue.replan(state)
            item, _ = queue.next_eligible(state, automatic=True)
            if not item:
                state["away"]["waiting"] = "Nothing in the backlog is eligible right now"
                self.save(state)
                return
            item.update(status="queued", approved_revision=item["revision"], approved_by="away_mode")
            try:
                await self.launch_mission(state, config, item, authorized_by="away")
                state["away"]["waiting"] = ""
            except ModelCheckError as exc:
                # Ollama down or a model missing is the environment, not a mission failure:
                # wait visibly and retry on the next tick, without tripping the breaker.
                item.update(status="available", approved_revision="")
                state["away"]["waiting"] = f"Waiting for local models: {exc}"
            except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
                item.update(status="available", approved_revision="")
                state["failures"] += 1
                state["away"]["waiting"] = f"Could not start {item['title']}: {exc}"
            self.save(state)

    # ----- loop -------------------------------------------------------------------------------

    async def tick(self):
        from .proactivity import get_away_mode
        async with self.lock:
            state = self.state()
            config = DevelopmentConfig.model_validate(state["config"])
            running = [run for run in state["runs"] if run["status"] == "running"]
            if running:
                policy = model_policy()
                if policy["held"]:
                    # The owner unloaded the models: stop before the worker's next request
                    # reloads them, keep its edits, and let the ticket run again later.
                    for run in running:
                        publish_model_policy(root() / run["id"], policy)
                    await self.halt(state, "you unloaded the models")
                    for run in running:
                        item = state["items"].get(run["item_id"])
                        if item and item.get("status") == "stopped":
                            item.update(status="available", attempted_revision="")
                    queue.replan(state)
                    self.save(state)
                else:
                    for run in running:
                        publish_model_policy(root() / run["id"], policy)
            for run in state["runs"]:
                if run["status"] != "running":
                    continue
                control = root() / run["id"]
                result = read_json(control / "result.json", None)
                expired = time.time() - run["started_at"] >= config.max_run_minutes * 60
                alive = self.owned_process(run)
                if result is None and alive and not expired and not kill_switch_active():
                    continue
                if alive:
                    await asyncio.to_thread(self.stop_process, run)
                if self.process:
                    self.process.poll()
                status = result.get("status", "failed") if result else ("timed_out" if expired else "interrupted")
                run.update(status=status, ended_at=time.time(), result=result or {"error": "Worker stopped without a verified result"})
                item = state["items"][run["item_id"]]
                delivery = state["deliveries"].get(run.get("delivery_id", ""))
                self.release()
                if delivery and delivery["stage"] in {"implementing", "repairing"}:
                    if status == "review_ready" and item["revision"] == delivery["revision"]:
                        self.set_stage(state, delivery, "testing", "Worker verification passed; controller testing")
                    else:
                        reason = (result or {}).get("error") or ((result or {}).get("verification") or {}).get("error") or f"Mission ended {status.replace('_', ' ')}"
                        self.attention(state, delivery, reason)
                else:
                    state["failures"] = 0 if status == "review_ready" else state["failures"] + 1
                    if item["revision"] == run["revision"]:
                        item.update(status=status, approved_revision="", attempted_revision=run["revision"])
                self.save(state)
            # Reconcile builds that were running across a restart without starting another.
            for sha, job in list(state["builds"].items()):
                if job["status"] == "running":
                    polled = await asyncio.to_thread(builds.poll, job)
                    if polled != job:
                        state["builds"][sha] = polled
                        delivery = next((d for d in state["deliveries"].values() if d.get("merge_sha") == sha), None)
                        if delivery and delivery["stage"] == "merged":
                            if polled["status"] == "succeeded":
                                state["failures"] = 0
                                self.set_stage(state, delivery, "delivered", f"Build ready: {polled['artifact']}")
                            else:
                                self.set_stage(state, delivery, "build_failed", polled["error"])
                        self.save(state)
            if state["away"]["enabled"] and not get_away_mode().enabled:
                # The owner switched general Away Mode off elsewhere: they are back.
                self.end_away(state, "Owner returned")
                await self.halt(state, "owner returned")
                self.save(state)
            pipeline = self.pipeline_next(state)
            busy = pipeline is not None or self.active_delivery(state) is not None or any(r["status"] == "running" for r in state["runs"])
            due = not busy and config.enabled and not config.resource_hold and time.time() >= state["next_run"] and state["failures"] < config.failure_limit and not kill_switch_active()
            if due:
                state["next_run"] = time.time() + config.interval_minutes * 60
                self.save(state)
            away = state["away"]["enabled"]
        if pipeline:
            await self.advance(pipeline["id"])
            return
        if due:
            await self.scan()
            await self.launch()
        if away:
            await self.away_dispatch()

    async def guarded_tick(self):
        try:
            await self.tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with self.lock:
                state = self.state()
                state["error"] = str(exc)
                self.save(state)

    async def loop(self):
        while True:
            await self.guarded_tick()
            await asyncio.sleep(5)

    async def start(self):
        if self.runner is None:
            # Adopt a surviving worker's lease; do not replay an interrupted task.
            state = self.state()
            if any(r["status"] == "running" and self.owned_process(r) for r in state["runs"]):
                self.claim()
            self.runner = asyncio.create_task(self.loop())

    async def close(self):
        for task in (self.kick, self.runner):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.kick = None
        self.runner = None
        # Preserve the schedule and Away Mode policy across clean app restarts. Active
        # edits are interrupted, checkpointed and remain reviewable; they are never replayed.
        async with self.lock:
            state = self.state()
            await self.halt(state, "ANZU shut down")
            self.save(state)


def spawn_worker(command, *, cwd: str, env: dict, stdout):
    """The separate mission process; no console window, no stdin."""
    return subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def pr_body(delivery) -> str:
    tests = delivery.get("tests") or {}
    review_record = delivery.get("review") or {}
    lines = [
        f"Automated ANZU self-development delivery for **{delivery['title']}** (RFC-0211 Away Mode).",
        "",
        f"- Ticket revision: `{delivery['revision'][:16]}`",
        f"- Base: `{delivery['base_ref']}` @ `{delivery['base_sha'][:12]}`",
        f"- Head reviewed and tested: `{review_record.get('head_sha', '')[:12]}`",
        f"- North Star blob: `{delivery.get('north_star_blob', '')[:12]}`",
        f"- Repairs: {delivery.get('repairs', 0)}",
        "",
        "## Controller verification",
    ]
    lines += [f"- `{' '.join(map(str, c['command']))}` → exit {c['returncode']}" for c in tests.get("checks", [])]
    lines += ["", "## Independent review", review_record.get("north_star", "") or "Approved with no blocker findings."]
    lines += [f"- [{f['severity']}] {f['file']}: {f['issue']}" for f in review_record.get("findings", [])]
    lines += ["", "ANZU merges this PR only while Away Mode is on and only at the reviewed head after all checks pass."]
    return "\n".join(lines)


DEVELOPMENT = DevelopmentScheduler()
