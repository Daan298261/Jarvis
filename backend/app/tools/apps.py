"""Launch, find, and close desktop applications by name.

The model asks for "steam" or "snipping tool"; this tool resolves that to what
Windows would open from the Start menu, launches it the way a double-click does
(ShellExecute), and confirms a matching process actually appeared. Resolution
order: Start Menu shortcuts → App Paths registry → PATH → Desktop / extra-drive
Program Files and PortableApps → Store (UWP) apps.
"""

from __future__ import annotations

import asyncio
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from .base import RiskLevel, Tool, ToolResult
from .safety import is_protected_process

_NOISE_WORDS = {"the", "app", "application", "program", "please", "my", "a", "an"}
_SKIP_SHORTCUT = re.compile(r"(?i)\b(uninstall|readme|help|support|website|manual|release notes|license)\b")
_UWP_TIMEOUT_S = 20.0
_UWP_CACHE: list[tuple[str, str]] | None = None
_APP_FILE_SUFFIXES = {".lnk", ".url", ".exe", ".appimage", ".desktop"}
_SKIP_DIR_NAMES = frozenset(
    {
        "windows",
        "windows.old",
        "windowsapps",
        "winsxs",
        "installer",
        "$recycle.bin",
        "recycle.bin",
        "system volume information",
        "node_modules",
        ".git",
    }
)
_POSIX_SKIP_MOUNTS = frozenset(
    {"/", "/boot", "/boot/efi", "/snap", "/sys", "/proc", "/dev", "/run"}
)


@dataclass
class AppTarget:
    name: str
    kind: str  # shortcut | exe | uwp
    target: str
    match_tokens: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "target": self.target}


def normalize_app_name(raw: str) -> str:
    text = re.sub(r"\.(exe|lnk)$", "", (raw or "").strip().lower())
    words = [word for word in re.split(r"[\s_\-]+", text) if word and word not in _NOISE_WORDS]
    return " ".join(words)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _score(query: str, candidate: str) -> int:
    """Higher is better; 0 means no match."""
    q, c = _compact(query), _compact(candidate)
    if not q or not c:
        return 0
    if q == c:
        return 100
    if c.startswith(q):
        return 80 - min(20, len(c) - len(q))
    if q in c:
        return 60 - min(20, len(c) - len(q))
    words = set(normalize_app_name(query).split())
    cand_words = set(normalize_app_name(candidate).split())
    if words and words <= cand_words:
        return 50
    return 0


def _start_menu_dirs() -> list[Path]:
    roots = []
    for env in ("ProgramData", "APPDATA"):
        base = os.environ.get(env)
        if base:
            roots.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [root for root in roots if root.is_dir()]


def _shortcuts() -> list[Path]:
    found: list[Path] = []
    for root in _start_menu_dirs():
        for dirpath, _dirs, files in os.walk(root):
            for filename in files:
                if filename.lower().endswith((".lnk", ".url")):
                    found.append(Path(dirpath) / filename)
    return found


def _portable_search_roots() -> list[tuple[Path, int]]:
    """Desktop plus Program Files / PortableApps on extra mounted volumes.

    The system-drive Program Files tree is already covered by Start Menu
    shortcuts; walking it again would scan thousands of files on every miss.
    Extra volumes (USB, D:, mapped drives) and Desktop shortcuts are not.
    """
    rows: list[tuple[Path, int]] = []
    seen: set[str] = set()

    def add(path: Path, depth: int) -> None:
        try:
            if not path.is_dir():
                return
        except OSError:
            return
        key = str(path).replace("\\", "/").lower().rstrip("/")
        if key in seen:
            return
        seen.add(key)
        rows.append((path, depth))

    add(Path.home() / "Desktop", 2)
    public = os.environ.get("PUBLIC")
    if public:
        add(Path(public) / "Desktop", 2)
    if os.name == "nt":
        from ..config import _windows_owner_drives

        system = os.path.normcase(str(Path.home().anchor).rstrip("\\"))
        for drive in _windows_owner_drives():
            add(drive / "PortableApps", 3)
            drive_key = os.path.normcase(str(drive).rstrip("\\"))
            if drive_key == system:
                continue
            add(drive / "Program Files", 3)
            add(drive / "Program Files (x86)", 3)
            add(drive, 2)
    else:
        from ..config import _posix_owner_roots

        for mount in _posix_owner_roots():
            if str(mount) in _POSIX_SKIP_MOUNTS:
                continue
            add(mount, 3)
    return rows


def _iter_app_files(root: Path, *, max_depth: int) -> list[Path]:
    found: list[Path] = []
    try:
        if not root.is_dir():
            return found
    except OSError:
        return found
    root_s = str(root)
    for dirpath, dirnames, files in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root_s)
        depth = 0 if rel in (".", os.curdir) else rel.count(os.sep) + 1
        dirnames[:] = [
            name
            for name in dirnames
            if name.lower() not in _SKIP_DIR_NAMES and not name.startswith(".")
        ]
        if depth >= max_depth:
            dirnames[:] = []
        for filename in files:
            if Path(filename).suffix.lower() in _APP_FILE_SUFFIXES:
                found.append(Path(dirpath) / filename)
    return found


def _portable_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".lnk", ".url"}:
        return "shortcut"
    return "exe"


def _best_portable(query: str) -> tuple[int, Path] | None:
    best: tuple[int, Path] | None = None
    for root, max_depth in _portable_search_roots():
        for path in _iter_app_files(root, max_depth=max_depth):
            if _SKIP_SHORTCUT.search(path.stem):
                continue
            score = _score(query, path.stem)
            if score and path.suffix.lower() == ".url":
                score -= 15
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, path)
            if score >= 100:
                return best
    return best


def _app_paths(query: str) -> str | None:
    if platform.system() != "Windows":
        return None
    import winreg

    exe = _compact(query) + ".exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value:
                    return str(value).strip('"')
        except OSError:
            continue
    return None


def _uwp_apps() -> list[tuple[str, str]]:
    """(display name, AppID) from Get-StartApps; slow, so cached per process."""
    global _UWP_CACHE
    if _UWP_CACHE is not None:
        return _UWP_CACHE
    if platform.system() != "Windows":
        _UWP_CACHE = []
        return _UWP_CACHE
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ForEach-Object { $_.Name + \"`t\" + $_.AppID }"],
            capture_output=True,
            text=True,
            timeout=_UWP_TIMEOUT_S,
        )
        rows = [line.split("\t", 1) for line in proc.stdout.splitlines() if "\t" in line]
        _UWP_CACHE = [(name.strip(), app_id.strip()) for name, app_id in rows if name.strip() and app_id.strip()]
    except (OSError, subprocess.TimeoutExpired):
        _UWP_CACHE = []
    return _UWP_CACHE


def resolve_app(raw_name: str) -> AppTarget | None:
    query = normalize_app_name(raw_name)
    if not query:
        return None
    tokens = [token for token in query.split() if len(token) >= 3] or [query]

    best: tuple[int, Path] | None = None
    for shortcut in _shortcuts():
        if _SKIP_SHORTCUT.search(shortcut.stem):
            continue
        score = _score(query, shortcut.stem)
        if score and shortcut.suffix.lower() == ".url":
            score -= 15  # web / game-library links rank below installed programs
        if score > 0 and (best is None or score > best[0]):
            best = (score, shortcut)
    # Exact or prefix shortcut matches win outright ("steam" -> Steam.lnk).
    if best is not None and best[0] >= 70:
        return AppTarget(best[1].stem, "shortcut", str(best[1]), tokens)

    # A registered executable with exactly this name beats a fuzzy shortcut
    # ("chrome" -> chrome.exe, not a game called "Neon Chrome").
    registered = _app_paths(query)
    if registered:
        return AppTarget(query, "exe", registered, tokens + [Path(registered).stem.lower()])
    on_path = shutil.which(_compact(query)) or shutil.which(query)
    if on_path:
        return AppTarget(query, "exe", on_path, tokens + [Path(on_path).stem.lower()])
    portable = _best_portable(query)
    if portable is not None and portable[0] >= 70:
        path = portable[1]
        return AppTarget(path.stem, _portable_kind(path), str(path), tokens + [path.stem.lower()])
    if best is not None and best[0] >= 45:
        return AppTarget(best[1].stem, "shortcut", str(best[1]), tokens)
    if portable is not None and portable[0] >= 45:
        path = portable[1]
        return AppTarget(path.stem, _portable_kind(path), str(path), tokens + [path.stem.lower()])

    uwp_best: tuple[int, str, str] | None = None
    for name, app_id in _uwp_apps():
        if _SKIP_SHORTCUT.search(name):
            continue
        score = _score(query, name)
        if score and (uwp_best is None or score > uwp_best[0]):
            uwp_best = (score, name, app_id)
    if uwp_best is not None and uwp_best[0] >= 50:
        return AppTarget(uwp_best[1], "uwp", uwp_best[2], tokens)
    return None


def _process_matches(proc: psutil.Process, tokens: list[str]) -> bool:
    try:
        name = _compact(proc.name())
        exe = _compact(Path(proc.exe()).stem) if proc.exe() else ""
    except (psutil.Error, OSError):
        return False
    return any(_compact(token) and (_compact(token) in name or _compact(token) in exe) for token in tokens)


def matching_processes(tokens: list[str]) -> list[psutil.Process]:
    out = []
    for proc in psutil.process_iter(["pid", "name"]):
        if _process_matches(proc, tokens):
            out.append(proc)
    return out


def _shell_open(target: str, *, elevated: bool) -> None:
    if platform.system() != "Windows":
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    if elevated:
        import ctypes

        code = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, None, None, 1)
        if int(code) <= 32:
            raise OSError(f"ShellExecute runas failed with code {code} (UAC declined or target invalid)")
        return
    os.startfile(target)  # type: ignore[attr-defined]


async def launch_app(raw_name: str, *, elevated: bool = False, verify_seconds: float = 20.0) -> ToolResult:
    target = resolve_app(raw_name)
    if target is None:
        return ToolResult(
            False,
            "",
            error=(
                f"No installed app matches {raw_name!r} (searched Start Menu, App Paths, PATH, "
                "Desktop, extra-drive Program Files / PortableApps, and Store apps). "
                "Use apps action=find to see close names."
            ),
        )
    already = {proc.pid for proc in matching_processes(target.match_tokens)}
    try:
        if target.kind == "uwp":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target.target}"])
        else:
            _shell_open(target.target, elevated=elevated)
    except OSError as exc:
        return ToolResult(False, "", error=f"Could not start {target.name}: {exc}", data=target.as_dict())

    deadline = time.monotonic() + max(1.0, verify_seconds)
    started: list[psutil.Process] = []
    while time.monotonic() < deadline:
        started = [proc for proc in matching_processes(target.match_tokens) if proc.pid not in already]
        if started or already:
            break
        await asyncio.sleep(0.5)
    data = {
        **target.as_dict(),
        "elevated": elevated,
        "already_running": bool(already) and not started,
        "pids": sorted({proc.pid for proc in started} | already),
    }
    if started:
        return ToolResult(True, f"Started {target.name} (pid {started[0].pid}).", data=data)
    if already:
        return ToolResult(True, f"{target.name} was already running; brought it forward.", data=data)
    return ToolResult(
        False,
        f"Asked Windows to open {target.name}, but no matching process appeared within {int(verify_seconds)}s.",
        data=data,
        error=f"{target.name} did not start",
    )


async def close_app(raw_name: str, *, force: bool = False) -> ToolResult:
    query = normalize_app_name(raw_name)
    target = resolve_app(raw_name)
    tokens = (target.match_tokens if target else []) or [token for token in query.split() if len(token) >= 3] or [query]
    session_id = _session_id(os.getpid())
    closable: list[psutil.Process] = []
    skipped: set[str] = set()
    for proc in matching_processes(tokens):
        try:
            name = proc.name()
        except psutil.Error:
            continue
        if is_protected_process(name, proc.pid):
            skipped.add(name)
            continue
        # Background services (e.g. steamservice.exe as SYSTEM) are not the app the
        # owner is looking at; closing them needs an elevated backend.
        if session_id is not None and _session_id(proc.pid) != session_id:
            skipped.add(name)
            continue
        closable.append(proc)
    if not closable:
        detail = f" (left running: {', '.join(sorted(skipped))})" if skipped else ""
        return ToolResult(False, "", error=f"No running app matches {raw_name!r}{detail}")

    names = sorted({_safe_name(proc) for proc in closable})
    denied: set[str] = set()
    for proc in closable:
        try:
            proc.kill() if force else proc.terminate()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            denied.add(_safe_name(proc))
    remaining = [proc for proc in closable if _safe_name(proc) not in denied]
    still = _wait_gone(remaining, 5.0)
    for proc in still:
        try:
            proc.kill()
        except psutil.Error:
            pass
    still = _wait_gone(still, 3.0)
    if still or denied:
        stuck = sorted({_safe_name(proc) for proc in still} | denied)
        return ToolResult(
            False,
            f"Closed {', '.join(n for n in names if n not in stuck) or 'nothing'}.",
            data={"closed": [n for n in names if n not in stuck], "not_closed": stuck},
            error=(
                f"{', '.join(stuck)} did not close"
                + (" (access denied — needs the elevated backend)" if denied else "")
            ),
        )
    return ToolResult(True, f"Closed {', '.join(names)}.", data={"closed": names, "count": len(closable)})


def _safe_name(proc: psutil.Process) -> str:
    try:
        return proc.name()
    except psutil.Error:
        return f"pid {proc.pid}"


def _session_id(pid: int) -> int | None:
    """Windows terminal-services session of ``pid`` (services run in session 0)."""
    if platform.system() != "Windows":
        return None
    import ctypes
    from ctypes import wintypes

    session = wintypes.DWORD()
    ok = ctypes.windll.kernel32.ProcessIdToSessionId(wintypes.DWORD(pid), ctypes.byref(session))
    return int(session.value) if ok else None


def _wait_gone(procs: list[psutil.Process], timeout: float) -> list[psutil.Process]:
    """Processes still alive after ``timeout``; never raises for inaccessible processes."""
    deadline = time.monotonic() + timeout
    alive = list(procs)
    while alive and time.monotonic() < deadline:
        alive = [proc for proc in alive if _is_alive(proc)]
        if alive:
            time.sleep(0.2)
    return alive


def _is_alive(proc: psutil.Process) -> bool:
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True


def find_apps(raw_name: str, limit: int = 12) -> ToolResult:
    query = normalize_app_name(raw_name)
    rows: list[tuple[int, str, str]] = []
    for shortcut in _shortcuts():
        score = _score(query, shortcut.stem) if query else 1
        if score and not _SKIP_SHORTCUT.search(shortcut.stem):
            rows.append((score, shortcut.stem, "shortcut"))
    for root, max_depth in _portable_search_roots():
        for path in _iter_app_files(root, max_depth=max_depth):
            if _SKIP_SHORTCUT.search(path.stem):
                continue
            score = _score(query, path.stem) if query else 1
            if score:
                rows.append((score, path.stem, _portable_kind(path)))
    for name, _app_id in _uwp_apps():
        score = _score(query, name) if query else 1
        if score:
            rows.append((score, name, "store app"))
    seen: set[str] = set()
    names: list[str] = []
    for _score_value, name, kind in sorted(rows, key=lambda row: (-row[0], row[1])):
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(f"{name} ({kind})")
        if len(names) >= limit:
            break
    return ToolResult(bool(names), "\n".join(names) or "No installed apps matched.", data={"apps": names})


class AppsTool(Tool):
    name = "apps"
    description = (
        "Open, find, or close desktop applications by their normal name (\"steam\", \"spotify\", "
        "\"snipping tool\"). Resolves the name the way the Start menu does, then Desktop shortcuts "
        "and Program Files / PortableApps on extra mounted drives, launches it like a "
        "double-click, and confirms the app's process started. Use this instead of shell commands "
        "for opening or closing programs. elevated=true runs it as administrator."
    )
    risk = RiskLevel.MEDIUM
    effect_class = "external"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open", "close", "find", "running"], "default": "open"},
            "name": {"type": "string", "description": "App name as the owner said it"},
            "elevated": {"type": "boolean", "default": False, "description": "Run as administrator"},
            "force": {"type": "boolean", "default": False, "description": "close: kill instead of asking to exit"},
        },
        "required": ["name"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "open").strip().lower()
        name = str(kwargs.get("name") or "").strip()
        if not name and action != "running":
            return ToolResult(False, "", error="name is required")
        if action == "open":
            return await launch_app(name, elevated=bool(kwargs.get("elevated")))
        if action == "close":
            return await close_app(name, force=bool(kwargs.get("force")))
        if action == "find":
            return await asyncio.to_thread(find_apps, name)
        if action == "running":
            tokens = [token for token in normalize_app_name(name).split() if len(token) >= 3] or [name]
            procs = matching_processes(tokens) if name else []
            names = sorted({proc.name() for proc in procs})
            return ToolResult(
                True,
                (f"Running: {', '.join(names)}" if names else f"No running process matches {name!r}."),
                data={"running": bool(names), "processes": names},
            )
        return ToolResult(False, "", error=f"Unknown action {action}")
