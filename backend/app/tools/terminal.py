from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import psutil

from .base import RiskLevel, Tool, ToolResult
from .safety import classify_command


@dataclass
class BackgroundJob:
    pid: int
    command: str
    proc: asyncio.subprocess.Process
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    started: float = field(default_factory=time.time)
    pump: asyncio.Task | None = None


_JOBS: dict[int, BackgroundJob] = {}


def _decode(data: bytes | bytearray) -> str:
    return bytes(data).decode("utf-8", errors="replace")


def _python_args(command: str) -> list[str]:
    stripped = (command or "").strip()
    python = sys.executable or shutil.which("python") or shutil.which("python3") or "python3"
    if not stripped:
        return [python, "-c", ""]
    first = stripped.split()[0]
    looks_like_file = first.endswith(".py") or (os.path.isfile(first) and not any(ch in stripped for ch in ";=\n"))
    if looks_like_file:
        return [python, *stripped.split()]
    return [python, "-c", command]


def default_shell() -> str:
    if sys.platform == "win32":
        return "powershell"
    if shutil.which("bash"):
        return "bash"
    return "python"


def _command_args(command: str, shell: str) -> list[str] | ToolResult:
    if shell == "powershell":
        exe = shutil.which("powershell") or shutil.which("pwsh")
        if not exe:
            return ToolResult(False, "", error="PowerShell is not available on this machine")
        return [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    if shell == "cmd":
        return ["cmd", "/c", command]
    if shell == "python":
        return _python_args(command)
    if shell == "git":
        if command.startswith("git"):
            return command.split()
        return ["git", *command.split()]
    if shell in {"bash", "wsl"}:
        if sys.platform == "win32" and shutil.which("wsl") and shell == "wsl":
            return ["wsl", "-e", "bash", "-lc", command]
        if shutil.which("bash"):
            return ["bash", "-lc", command]
        return ToolResult(False, "", error="WSL/bash is not available on this machine")
    return _command_args(command, default_shell())


async def _pump(job: BackgroundJob) -> None:
    async def _read(stream, bucket: bytearray) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            bucket.extend(chunk)
            if len(bucket) > 200_000:
                del bucket[:-120_000]

    await asyncio.gather(_read(job.proc.stdout, job.stdout), _read(job.proc.stderr, job.stderr))


def _job_snapshot(job: BackgroundJob, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    alive = job.proc.returncode is None
    payload = {
        "pid": job.pid,
        "alive": alive,
        "command": job.command,
        "elapsed_seconds": round(time.time() - job.started, 2),
        "exit_code": job.proc.returncode,
        "stdout": _decode(job.stdout)[-8000:],
        "stderr": _decode(job.stderr)[-4000:],
    }
    if extra:
        payload.update(extra)
    return payload


def _format_inspect(payload: dict[str, Any]) -> str:
    lines = [
        f"pid={payload.get('pid')}",
        f"alive={payload.get('alive')}",
        f"status={payload.get('status') or ('running' if payload.get('alive') else 'exited')}",
        f"command={payload.get('command') or ''}",
        f"elapsed_seconds={payload.get('elapsed_seconds', '')}",
        f"exit_code={payload.get('exit_code') if payload.get('exit_code') is not None else ''}",
    ]
    if payload.get("cpu_percent") is not None:
        lines.append(f"cpu_percent={payload['cpu_percent']}")
    if payload.get("rss_mb") is not None:
        lines.append(f"rss_mb={payload['rss_mb']}")
    if "stdout" in payload:
        lines.append("--- stdout ---")
        lines.append(payload.get("stdout") or "")
        lines.append("--- stderr ---")
        lines.append(payload.get("stderr") or "")
    return "\n".join(lines)


class TerminalTool(Tool):
    name = "terminal"
    description = (
        "Run a local command. shell can be powershell, cmd, python, git, or bash/wsl. "
        "Default shell is PowerShell on Windows and bash on Linux. "
        "action=run (default) waits for the process. action=start returns a PID immediately; "
        "then use inspect/wait/kill with that pid to see if it is still alive and to collect output. "
        "inspect also works for other local PIDs. Captures stdout, stderr, exit code and duration. "
        "Use working_directory when possible. Do not use this to format disks or destroy backups."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "shell": {
                "type": "string",
                "enum": ["powershell", "cmd", "python", "git", "bash", "wsl"],
            },
            "working_directory": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 120},
            "action": {
                "type": "string",
                "enum": ["run", "start", "inspect", "wait", "kill"],
                "default": "run",
                "description": "run waits; start backgrounds; inspect/wait/kill use pid",
            },
            "pid": {"type": "integer", "description": "Process id for inspect, wait, or kill"},
            "background": {"type": "boolean", "default": False, "description": "If true, treated as action=start"},
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = (kwargs.get("action") or "run").lower()
        if kwargs.get("background") and action == "run":
            action = "start"
        if action == "inspect":
            return await self._inspect(kwargs.get("pid"))
        if action == "wait":
            return await self._wait(kwargs.get("pid"), int(kwargs.get("timeout_seconds") or 120))
        if action == "kill":
            return await self._kill(kwargs.get("pid"))

        command = kwargs.get("command") or ""
        if not command.strip():
            return ToolResult(False, "", error="command is required for run/start")
        shell = (kwargs.get("shell") or default_shell()).lower()
        cwd = kwargs.get("working_directory") or os.getcwd()
        timeout = int(kwargs.get("timeout_seconds") or 120)
        risk = classify_command(command)
        if risk == RiskLevel.IRREVERSIBLE:
            return ToolResult(False, "", error="Blocked irreversible command. Ask the user explicitly if this is required.")
        args = _command_args(command, shell)
        if isinstance(args, ToolResult):
            return args
        if action == "start":
            return await self._start(args, command, cwd)
        return await self._run(args, cwd, timeout)

    async def _run(self, args: list[str], cwd: str, timeout: int) -> ToolResult:
        started = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(False, "", error=f"Command timed out after {timeout}s", data={"pid": proc.pid})
            duration = round((time.time() - started) * 1000, 1)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            code = proc.returncode or 0
            text = (
                f"exit_code={code}\nduration_ms={duration}\npid={proc.pid}\n"
                f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
            )
            return ToolResult(
                code == 0,
                text,
                data={"exit_code": code, "duration_ms": duration, "pid": proc.pid, "alive": False},
                error="" if code == 0 else err[-2000:],
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

    async def _start(self, args: list[str], command: str, cwd: str) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
        if proc.pid is None:
            return ToolResult(False, "", error="Process started without a PID")
        job = BackgroundJob(pid=proc.pid, command=command, proc=proc)
        job.pump = asyncio.create_task(_pump(job))
        _JOBS[proc.pid] = job
        payload = _job_snapshot(job)
        return ToolResult(
            True,
            f"started pid={proc.pid}\ncommand={command}\nUse terminal action=inspect/wait/kill with this pid.",
            data=payload,
        )

    async def _inspect(self, pid: Any) -> ToolResult:
        if pid in (None, "", 0):
            jobs = [_job_snapshot(job) for job in list(_JOBS.values())]
            text = "No tracked background jobs." if not jobs else "\n\n".join(_format_inspect(item) for item in jobs)
            return ToolResult(True, text, data={"jobs": jobs})
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            return ToolResult(False, "", error="pid must be an integer")
        extra: dict[str, Any] = {}
        job = _JOBS.get(pid_i)
        if job:
            payload = _job_snapshot(job)
        else:
            payload = {"pid": pid_i, "command": "", "stdout": "", "stderr": ""}
        try:
            proc = psutil.Process(pid_i)
            payload["alive"] = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            payload["status"] = proc.status()
            payload["command"] = payload.get("command") or " ".join(proc.cmdline()) or proc.name()
            payload["cpu_percent"] = proc.cpu_percent(interval=0.05)
            payload["rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 2)
            if payload.get("elapsed_seconds") is None:
                payload["elapsed_seconds"] = round(max(0.0, time.time() - proc.create_time()), 2)
        except psutil.NoSuchProcess:
            payload["alive"] = False
            payload["status"] = "not_found"
            payload["exit_code"] = job.proc.returncode if job else None
        extra.update(payload)
        return ToolResult(True, _format_inspect(payload), data=payload)

    async def _wait(self, pid: Any, timeout: int) -> ToolResult:
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            return ToolResult(False, "", error="pid is required for wait")
        job = _JOBS.get(pid_i)
        if not job:
            return ToolResult(False, "", error=f"PID {pid_i} is not a process started by Jarvis")
        try:
            await asyncio.wait_for(job.proc.wait(), timeout=timeout)
        except TimeoutError:
            payload = _job_snapshot(job)
            payload["timed_out"] = True
            return ToolResult(False, _format_inspect(payload), data=payload, error=f"Still running after {timeout}s")
        if job.pump:
            try:
                await asyncio.wait_for(job.pump, timeout=2)
            except TimeoutError:
                pass
        payload = _job_snapshot(job)
        code = job.proc.returncode or 0
        return ToolResult(code == 0, _format_inspect(payload), data=payload, error="" if code == 0 else (payload.get("stderr") or "")[-2000:])

    async def _kill(self, pid: Any) -> ToolResult:
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            return ToolResult(False, "", error="pid is required for kill")
        job = _JOBS.get(pid_i)
        if job and job.proc.returncode is None:
            job.proc.kill()
            await job.proc.wait()
            if job.pump:
                try:
                    await asyncio.wait_for(job.pump, timeout=2)
                except TimeoutError:
                    pass
            payload = _job_snapshot(job, extra={"killed": True, "alive": False})
            return ToolResult(True, _format_inspect(payload), data=payload)
        try:
            proc = psutil.Process(pid_i)
        except psutil.NoSuchProcess:
            return ToolResult(False, "", error=f"PID {pid_i} is not running")
        # Only kill processes Jarvis started, or their remaining children tracked here.
        return ToolResult(
            False,
            "",
            error=f"Refusing to kill PID {pid_i} ({proc.name()}) because Jarvis did not start it.",
        )
