"""Copy docker images with skopeo so LAN registries bind the home NIC.

Dockerd cannot source-bind. Terminal ``docker compose pull`` / ``push`` /
``build`` / ``up`` / ``create`` / ``run`` and ``docker pull`` / ``push`` /
``build`` / ``buildx build`` / ``buildx bake`` of on-link RFC1918 images
inherit the loopback LAN HTTP proxy via this helper. ``--push`` copies
docker-daemon → docker://; the default loads docker:// → docker-daemon.
``--push-after`` uploads daemon images after an optional follow command.
A second ``--`` after follow runs a Hub compose-push. ``--all-tags`` expands
local daemon tags (push) or ``skopeo list-tags`` (pull).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys


def _repo_without_tag(repo: str) -> str:
    text = str(repo or "").strip()
    if text.lower().startswith("docker://"):
        text = text[9:]
    leaf = text.rsplit("/", 1)[-1]
    if "@" in leaf:
        text = text.split("@", 1)[0]
        leaf = text.rsplit("/", 1)[-1]
    if ":" in leaf:
        return text.rsplit(":", 1)[0]
    return text


def _expand_all_tags(exe: str, repo: str, *, push: bool) -> list[str] | None:
    name = _repo_without_tag(repo)
    if not name:
        return []
    if push:
        docker = shutil.which("docker") or shutil.which("docker.exe") or "docker"
        proc = subprocess.run(
            [docker, "image", "ls", "--format", "{{.Repository}}:{{.Tag}}", name],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode:
            return None
        tags: list[str] = []
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line or "<none>" in line:
                continue
            if line == name or line.startswith(f"{name}:"):
                tags.append(line)
        return tags
    proc = subprocess.run(
        [exe, "list-tags", "--tls-verify=false", f"docker://{name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        return None
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    raw = payload.get("Tags") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    return [f"{name}:{item}" for item in raw if str(item).strip() and "<none>" not in str(item)]


def _copy(exe: str, image: str, *, quiet: bool, push: bool, extra: list[str] | None = None) -> int:
    cmd = [exe, "copy"]
    if extra:
        cmd.extend(extra)
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
    all_tags = False
    extra: list[str] = []
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
        if args[0] in {"-a", "--all-tags"}:
            all_tags = True
            args = args[1:]
            continue
        if args[0] in {"--override-os", "--override-arch", "--override-variant"} and len(args) > 1:
            extra.extend([args[0], args[1]])
            args = args[2:]
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
    then: list[str] = []
    if "--" in args:
        cut = args.index("--")
        rest = args[cut + 1 :]
        args = args[:cut]
        if "--" in rest:
            cut2 = rest.index("--")
            follow = rest[:cut2]
            then = rest[cut2 + 1 :]
        else:
            follow = rest
    if not args:
        return 2
    exe, *images = args
    if not exe:
        return 2
    if all_tags:
        expanded: list[str] = []
        for image in images:
            tags = _expand_all_tags(exe, image, push=push)
            if tags is None:
                return 1
            expanded.extend(tags)
        images = expanded
        if not images and not push_after:
            return 1
    for image in images:
        code = _copy(exe, image, quiet=quiet, push=push, extra=extra)
        if code:
            return code
    if follow:
        proc = subprocess.run(follow, check=False)
        if proc.returncode:
            return int(proc.returncode)
    for image in push_after:
        code = _copy(exe, image, quiet=quiet, push=True, extra=extra)
        if code:
            return code
    if then:
        proc = subprocess.run(then, check=False)
        if proc.returncode:
            return int(proc.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
