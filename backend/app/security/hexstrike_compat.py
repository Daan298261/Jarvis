"""Fail-closed HexStrike launch shim (RFC-0086 / Codex dependency audit).

Upstream `hexstrike_server.py` imports mitmproxy (and optionally selenium) at
module import. Those extras resolve to vulnerable packages on Python 3.11 and
are outside Jarvis's defensive surface. This shim:

- refuses to start unless core Flask/requests/psutil are present
- stubs the proxy/browser extras so the reviewed server can bind loopback
- never installs mitmproxy, pwntools, or angr
- records which extras are stubbed so Jarvis status/catalog never call them "running"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

REQUIRED_MODULES = ("flask", "requests", "psutil")
PROXY_STUBS = (
    "mitmproxy",
    "mitmproxy.http",
    "mitmproxy.tools",
    "mitmproxy.tools.dump",
    "mitmproxy.options",
)
BROWSER_STUBS = (
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.common",
    "selenium.webdriver.common.by",
    "selenium.webdriver.support",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
    "selenium.common",
    "selenium.common.exceptions",
)

STUB_MARKER = "__jarvis_hexstrike_stub__"
STUB_MANIFEST_NAME = "optional-stubs.json"

DISABLED_MESSAGE = (
    "HexStrike proxy/browser extras are disabled in the Jarvis managed environment"
)

# Packages Jarvis intentionally stubs / refuses to treat as live operator deps.
ALWAYS_STUBBED_OPTIONALS = ("mitmproxy", "selenium")


class DisabledExtraError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(DISABLED_MESSAGE)


class _Stub:
    def __init__(self, name: str = "hexstrike_stub") -> None:
        self._name = name

    def __getattr__(self, name: str) -> "_Stub":
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub(f"{self._name}.{name}")

    def __call__(self, *args, **kwargs):
        raise DisabledExtraError()

    def __iter__(self):
        return iter(())

    def __bool__(self) -> bool:
        return False


def _ensure_required() -> None:
    missing: list[str] = []
    for name in REQUIRED_MODULES:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    if missing:
        raise SystemExit(
            "HexStrike managed environment is missing required packages: "
            + ", ".join(missing)
            + ". Re-run scripts/bootstrap-hexstrike.ps1 (core deps only)."
        )


def stub_manifest_path(state_root: Path | str | None = None) -> Path:
    if state_root is None:
        env = (os.environ.get("JARVIS_HEXSTRIKE_STATE_DIR") or "").strip()
        root = Path(env) if env else Path.cwd() / "jarvis-state"
    else:
        root = Path(state_root)
    return root / STUB_MANIFEST_NAME


def write_stub_manifest(stubbed: list[str], state_root: Path | str) -> Path:
    """Persist which optional packages are stubs (never live/running)."""
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "status": "unavailable",
        "stubbed": sorted({str(item).strip().lower() for item in stubbed if str(item).strip()}),
        "message": DISABLED_MESSAGE,
        "invokable": False,
    }
    target = stub_manifest_path(root)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
    return target


def read_stub_manifest(state_root: Path | str | None = None) -> dict[str, Any]:
    """Read the stub honesty manifest. Missing file → empty (no live claim)."""
    path = stub_manifest_path(state_root)
    if not path.is_file():
        return {
            "version": 1,
            "status": "unavailable",
            "stubbed": [],
            "message": "",
            "invokable": False,
            "present": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "version": 1,
            "status": "unavailable",
            "stubbed": list(ALWAYS_STUBBED_OPTIONALS),
            "message": DISABLED_MESSAGE,
            "invokable": False,
            "present": True,
            "corrupt": True,
        }
    if not isinstance(payload, dict):
        return {
            "version": 1,
            "status": "unavailable",
            "stubbed": list(ALWAYS_STUBBED_OPTIONALS),
            "message": DISABLED_MESSAGE,
            "invokable": False,
            "present": True,
            "corrupt": True,
        }
    stubbed = payload.get("stubbed") or []
    cleaned = [str(item).strip().lower() for item in stubbed if str(item).strip()]
    return {
        "version": int(payload.get("version") or 1),
        "status": "unavailable",
        "stubbed": cleaned,
        "message": str(payload.get("message") or DISABLED_MESSAGE),
        "invokable": False,
        "present": True,
    }


def package_is_stubbed(name: str, stubbed: list[str] | tuple[str, ...] | None = None) -> bool:
    """True when a tool/package name is covered by an active Jarvis optional stub."""
    needle = (name or "").strip().lower().replace("-", "_")
    if not needle:
        return False
    active = stubbed if stubbed is not None else ALWAYS_STUBBED_OPTIONALS
    for stub in active:
        token = str(stub).strip().lower().replace("-", "_")
        if not token:
            continue
        if needle == token or needle.startswith(f"{token}.") or token in needle.split("_") or token in needle.split("."):
            return True
        if token in needle:
            return True
    return False


def _install_stub_tree(names: tuple[str, ...]) -> None:
    created: dict[str, types.ModuleType] = {}
    for name in names:
        if name in sys.modules:
            module = sys.modules[name]
            setattr(module, STUB_MARKER, True)
            created[name] = module
            continue
        module = types.ModuleType(name)
        module.__dict__["__path__"] = []  # mark as package
        setattr(module, STUB_MARKER, True)
        sys.modules[name] = module
        created[name] = module
        parent_name, _, child = name.rpartition(".")
        if parent_name and parent_name in sys.modules:
            setattr(sys.modules[parent_name], child, module)
    for module in created.values():
        setattr(module, STUB_MARKER, True)
        for attr in (
            "By",
            "DumpMaster",
            "Options",
            "WebDriverWait",
            "WebDriverException",
            "TimeoutException",
            "http",
            "webdriver",
        ):
            if not hasattr(module, attr):
                setattr(module, attr, _Stub(attr))


def install_optional_stubs(*, force: bool = False) -> list[str]:
    """Install proxy/browser stubs when the real packages are absent (or force)."""
    stubbed: list[str] = []
    try:
        if force:
            raise ImportError("forced stub")
        import mitmproxy  # noqa: F401
        if getattr(sys.modules.get("mitmproxy"), STUB_MARKER, False):
            stubbed.append("mitmproxy")
    except Exception:
        _install_stub_tree(PROXY_STUBS)
        stubbed.append("mitmproxy")
    try:
        if force:
            raise ImportError("forced stub")
        import selenium  # noqa: F401
        if getattr(sys.modules.get("selenium"), STUB_MARKER, False):
            stubbed.append("selenium")
    except Exception:
        _install_stub_tree(BROWSER_STUBS)
        stubbed.append("selenium")
    return stubbed


def launch_reviewed_server(server: Path, argv: list[str] | None = None) -> None:
    path = Path(server).resolve()
    if not path.is_file():
        raise SystemExit(f"HexStrike server not found: {path}")
    if path.name != "hexstrike_server.py":
        raise SystemExit("refusing to launch an unexpected server file")
    _ensure_required()
    stubbed = install_optional_stubs(force=True)
    state_root = Path(
        os.environ.get("JARVIS_HEXSTRIKE_STATE_DIR", path.parent / "jarvis-state")
    ).resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    write_stub_manifest(stubbed or list(ALWAYS_STUBBED_OPTIONALS), state_root)
    source = path.read_text(encoding="utf-8")
    replacements = {
        'base_dir: str = "/tmp/hexstrike_envs"': f"base_dir: str = {str(state_root / 'python-envs')!r}",
        'base_dir: str = "/tmp/hexstrike_files"': f"base_dir: str = {str(state_root / 'files')!r}",
        'app.run(host="0.0.0.0", port=API_PORT, debug=DEBUG_MODE)': (
            'app.run(host=API_HOST, port=API_PORT, debug=DEBUG_MODE)'
        ),
    }
    for marker, replacement in replacements.items():
        if source.count(marker) != 1:
            raise SystemExit(f"refusing unexpected pinned source layout: {marker}")
        source = source.replace(marker, replacement)
    sys.argv = [str(path), *(argv or [])]
    namespace = {
        "__name__": "__main__",
        "__file__": str(path),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(source, str(path), "exec"), namespace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch HexStrike through the Jarvis fail-closed shim")
    parser.add_argument("--server", required=True, help="Path to hexstrike_server.py")
    parser.add_argument("--port", default=None)
    parser.add_argument("passthrough", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    extra: list[str] = []
    if args.port:
        extra.extend(["--port", str(args.port)])
    extra.extend(arg for arg in (args.passthrough or []) if arg != "--")
    launch_reviewed_server(Path(args.server), extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
