"""Load docker images with skopeo so LAN registries bind the home NIC.

Dockerd cannot source-bind. Terminal ``docker compose pull`` and ``docker build``
of on-link RFC1918 images inherit the loopback LAN HTTP proxy via this helper.
"""
from __future__ import annotations

import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    quiet = False
    if args and args[0] in {"-q", "--quiet"}:
        quiet = True
        args = args[1:]
    follow: list[str] = []
    if "--" in args:
        cut = args.index("--")
        follow = args[cut + 1 :]
        args = args[:cut]
    if not args:
        return 2
    exe, *images = args
    if not exe or not images:
        return 2
    for image in images:
        cmd = [exe, "copy"]
        if quiet:
            cmd.append("--quiet")
        cmd.extend(["--src-tls-verify=false", f"docker://{image}", f"docker-daemon:{image}"])
        proc = subprocess.run(cmd, check=False)
        if proc.returncode:
            return int(proc.returncode)
    if follow:
        proc = subprocess.run(follow, check=False)
        return int(proc.returncode or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
