"""Private owner directories on both Windows and POSIX hosts."""
from __future__ import annotations

import csv
import functools
import os
import subprocess
import shutil
from pathlib import Path


@functools.lru_cache(maxsize=1)
def owner_sid() -> str:
    value = subprocess.check_output(["whoami.exe", "/user", "/fo", "csv", "/nh"],
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    row = next(csv.reader(value.decode(errors="replace").strip().splitlines()))
    if len(row) != 2 or not row[1].startswith("S-1-"):
        raise RuntimeError("Could not determine the owner SID for private analysis data")
    return row[1]


def private_directory(path: Path):
    if path.exists():
        return
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "nt":
        try:
            subprocess.run(["icacls.exe", str(path), "/inheritance:r", "/grant:r",
                            "*" + owner_sid() + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                           check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except BaseException:
            # This call created the directory; never reuse a failed private root.
            shutil.rmtree(path)
            raise
