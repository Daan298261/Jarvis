"""Fail-closed HexStrike launch shim (RFC-0086 / Codex dependency audit).

Upstream `hexstrike_server.py` imports mitmproxy (and optionally selenium) at
module import. Those extras resolve to vulnerable packages on Python 3.11 and
are outside Jarvis's defensive surface. This shim:

- refuses to start unless core Flask/requests/psutil are present
- stubs the proxy/browser extras so the reviewed server can bind loopback
- never installs mitmproxy, pwntools, or angr
"""
from __future__ import annotations

import argparse
import runpy
import sys
import types
from pathlib import Path

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

DISABLED_MESSAGE = (
    "HexStrike proxy/browser extras are disabled in the Jarvis managed environment"
)


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


def _install_stub_tree(names: tuple[str, ...]) -> None:
    created: dict[str, types.ModuleType] = {}
    for name in names:
        if name in sys.modules:
            created[name] = sys.modules[name]
            continue
        module = types.ModuleType(name)
        module.__dict__["__path__"] = []  # mark as package
        sys.modules[name] = module
        created[name] = module
        parent_name, _, child = name.rpartition(".")
        if parent_name and parent_name in sys.modules:
            setattr(sys.modules[parent_name], child, module)
    for module in created.values():
        for attr in ("DumpMaster", "Options", "http", "webdriver", "TimeoutException", "WebDriverException"):
            if not hasattr(module, attr):
                setattr(module, attr, _Stub(attr))


def install_optional_stubs(*, force: bool = False) -> list[str]:
    """Install proxy/browser stubs when the real packages are absent (or force)."""
    stubbed: list[str] = []
    try:
        if force:
            raise ImportError("forced stub")
        import mitmproxy  # noqa: F401
    except Exception:
        _install_stub_tree(PROXY_STUBS)
        stubbed.append("mitmproxy")
    try:
        if force:
            raise ImportError("forced stub")
        import selenium  # noqa: F401
    except Exception:
        _install_stub_tree(BROWSER_STUBS)
        stubbed.append("selenium")
    return stubbed


def launch_reviewed_server(server: Path, argv: list[str] | None = None) -> None:
    path = Path(server)
    if not path.is_file():
        raise SystemExit(f"HexStrike server not found: {path}")
    _ensure_required()
    install_optional_stubs()
    sys.argv = [str(path), *(argv or [])]
    runpy.run_path(str(path), run_name="__main__")


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
