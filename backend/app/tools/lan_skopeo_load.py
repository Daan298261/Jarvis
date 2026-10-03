"""Copy docker images with skopeo so LAN registries bind the home NIC.

Dockerd cannot source-bind. Terminal ``docker compose pull`` / ``push`` /
``build`` / ``up`` / ``create`` / ``run`` and ``docker pull`` / ``push`` /
``build`` / ``buildx build`` / ``buildx bake`` of on-link RFC1918 images
inherit the loopback LAN HTTP proxy via this helper. ``--push`` copies
docker-daemon → docker://; the default loads docker:// → docker-daemon.
``--push-after`` uploads daemon images after an optional follow command.
"""
from __future__ import annotations

import subprocess
import sys


def _copy(exe: str, image: str, *, quiet: bool, push: bool) -> int:
    cmd = [exe, "copy"]
    if quiet:
        cmd.append("--quiet")
    if push:
        cmd.extend(["--dest-tls-verify=false", f"docker-daemon:{image}", f"docker://{image}"])
    else:
        cmd.extend(["--src-tls-verify=false", f"docker://{image}", f"docker-daemon:{image}"])
    return int(subprocess.run(cmd, check=False).returncode or 0)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    quiet = False
    push = False
    push_after: list[str] = []
    while args:
        if args[0] in {"-q", "--quiet"}:
            quiet = True
            args = args[1:]
            continue
        if args[0] == "--push":
            push = True
            args = args[1:]
            continue
        if args[0] == "--push-after" and len(args) > 1:
            push_after.append(args[1])
            args = args[2:]
            continue
        if args[0].startswith("--push-after="):
            push_after.append(args[0].split("=", 1)[1])
            args = args[1:]
            continue
        break
    follow: list[str] = []
    if "--" in args:
        cut = args.index("--")
        follow = args[cut + 1 :]
        args = args[:cut]
    if not args:
        return 2
    exe, *images = args
    if not exe:
        return 2
    for image in images:
        code = _copy(exe, image, quiet=quiet, push=push)
        if code:
            return code
    if follow:
        proc = subprocess.run(follow, check=False)
        if proc.returncode:
            return int(proc.returncode)
    for image in push_after:
        code = _copy(exe, image, quiet=quiet, push=True)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
