"""Smoke the packaged Windows backend and the portal shipped with JarvisSetup."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    exe = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else root / "installer/windows/payload/desktop/sidecars/jarvis-backend/jarvis-backend.exe"
    )
    if not exe.is_file():
        raise SystemExit(f"Packaged backend missing: {exe}")
    try:
        with socket.create_connection(("127.0.0.1", 4780), timeout=1):
            raise SystemExit("Port 4780 is already occupied; cannot smoke the packaged backend")
    except OSError:
        pass

    env = dict(os.environ, JARVIS_ROOT=str(root), JARVIS_SKIP_MODEL="1")
    log = Path(tempfile.gettempdir()) / "jarvis-151-backend-smoke.log"
    with log.open("wb") as output:
        proc = subprocess.Popen(
            [str(exe)],
            cwd=root,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and proc.poll() is None:
                try:
                    with urlopen("http://127.0.0.1:4780/api/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except (OSError, URLError):
                    time.sleep(1)
            else:
                raise RuntimeError(f"Packaged backend failed to become healthy; see {log}")

            with urlopen("http://127.0.0.1:4780/", timeout=5) as response:
                html = response.read().decode("utf-8")
                if response.status != 200:
                    raise RuntimeError(f"Portal returned {response.status}")
            asset = re.search(r'/assets/[^" ]+\.js', html)
            if not asset:
                raise RuntimeError("Portal index has no JavaScript asset")
            with urlopen("http://127.0.0.1:4780" + asset.group(), timeout=10) as response:
                body = response.read()
                if response.status != 200 or not body:
                    raise RuntimeError("Portal JavaScript asset is missing")
            print(f"health=200 portal=200 js=200 bytes={len(body)}")
            return 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
