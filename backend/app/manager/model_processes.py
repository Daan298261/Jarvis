"""Local emergency controls, independent of core health and model HTTP APIs."""
from __future__ import annotations

import hashlib
from pathlib import PureWindowsPath

import psutil

from ..inference.running_models import process_kind


def _identity(pid: int, name: str, created: float) -> str:
    return hashlib.sha256(f"{pid}:{name}:{created}".encode()).hexdigest()[:24]


def _kind(name: str, command: list[str]) -> str | None:
    if not name.casefold().removesuffix(".exe").startswith("python"):
        return process_kind(name, command)
    # Discovery's broad argv hints require HTTP verification. Emergency kills
    # instead require an explicit server entrypoint, never a data-file argument.
    args = command[1:]
    while args and args[0] in {"-u", "-B", "-E", "-s", "-S", "-I", "-O", "-OO"}:
        args = args[1:]
    if len(args) >= 2 and args[0] == "-m":
        return {"vllm.entrypoints.openai.api_server": "vllm",
                "vllm.entrypoints.api_server": "vllm",
                "sglang.launch_server": "sglang"}.get(args[1])
    if args:
        entry = PureWindowsPath(args[0])
        if entry.name.casefold() == "koboldcpp.py":
            return "koboldcpp"
        if entry.name.casefold() == "server.py" and entry.parent.name.casefold() in {
            "text-generation-webui", "oobabooga"
        }:
            return "textgen"
    return None


def _describe(process: psutil.Process) -> dict | None:
    name = process.name()
    try:
        command = process.cmdline()
        error = ""
    except psutil.AccessDenied:
        command = []
        error = "Permission denied: run Manager with the process owner's permissions."
    kind = _kind(name, command)
    if not kind:
        return None
    # Ollama's short-lived CLI clients are not model servers.
    if kind == "ollama" and command and (len(command) < 2 or command[1] not in {"serve", "runner"}):
        return None
    created = process.create_time()
    model = ""
    model_flags = {"--model", "--model-path", "--model-id"}
    if not name.casefold().removesuffix(".exe").startswith("python"):
        model_flags.add("-m")
    for index, arg in enumerate(command):
        if arg in model_flags and index + 1 < len(command):
            model = PureWindowsPath(command[index + 1]).name
            break
        if arg.startswith(("--model=", "--model-path=", "--model-id=")):
            model = PureWindowsPath(arg.split("=", 1)[1]).name
            break
    try:
        rss = process.memory_info().rss
    except psutil.AccessDenied:
        rss = None
    return {"id": _identity(process.pid, name, created), "pid": process.pid,
            "name": name, "kind": kind, "created": created, "model": model,
            "status": process.status(), "rss_bytes": rss,
            "can_kill": not error, "error": error}


def snapshot() -> dict:
    rows, inaccessible = [], 0
    for process in psutil.process_iter():
        try:
            row = _describe(process)
            if row:
                rows.append(row)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            inaccessible += 1
    return {"processes": sorted(rows, key=lambda row: (row["kind"], row["pid"])),
            "warning": (f"{inaccessible} processes could not be inspected. " if inaccessible else "")
            + "Recognized local model servers and workers, including ANZU's own models. "
              "Hard kill interrupts active work. A server may host multiple models; "
              "its parent application may restart it."}


def hard_kill(identifier: str) -> dict:
    row = next((r for r in snapshot()["processes"] if r["id"] == identifier), None)
    if row is None:
        raise ValueError("Process changed or is no longer running. Refresh the list.")
    if not row["can_kill"]:
        raise ValueError(row["error"])
    try:
        process = psutil.Process(row["pid"])
        # Re-read identity and classification immediately before kill: never use
        # a cached PID, name alone, caller-supplied argv, or process-tree kill.
        current = _describe(process)
        if current is None or current["id"] != identifier or not current["can_kill"]:
            raise ValueError("Process identity changed. Refresh the list.")
        process.kill()
        process.wait(timeout=5)
    except psutil.AccessDenied as exc:
        raise ValueError("Permission denied: the process could not be killed.") from exc
    except psutil.NoSuchProcess as exc:
        raise ValueError("Process is no longer running. Refresh the list.") from exc
    except psutil.TimeoutExpired as exc:
        raise ValueError("Kill was sent, but process exit was not confirmed. Refresh the list.") from exc
    return {"ok": True, "pid": row["pid"], "name": row["name"]}
