"""Copy docker images with skopeo so LAN registries bind the home NIC.

Dockerd cannot source-bind. Terminal ``docker compose pull`` / ``push`` /
``build`` / ``up`` / ``create`` / ``run`` and ``docker pull`` / ``push`` /
``build`` / ``buildx build`` / ``buildx bake`` of on-link RFC1918 images
inherit the loopback LAN HTTP proxy via this helper. ``--push`` copies
docker-daemon → docker://; the default loads docker:// → docker-daemon.
``--push-after`` uploads daemon images after an optional follow command.
A second ``--`` after follow runs a Hub compose-push. ``--all-tags`` expands
local daemon tags (push) or ``skopeo list-tags`` (pull). ``--fetch URL=path``
downloads Dockerfile ``ADD http(s)|ftp(s)://`` of on-link RFC1918 URLs through
the same proxy (and sitecustomize bind) before the follow ``docker build``.
``--python-copy`` pulls/pushes via the OCI distribution API and ``docker load``
/ ``docker save`` when skopeo is not on PATH. urllib honors HTTP_PROXY.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


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
    if not exe:
        return _python_list_tags(repo)
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


def _fetch(url: str, outfile: str) -> int:
    """Download one ADD URL. HTTP_PROXY / sitecustomize bind the home NIC."""
    dest = str(outfile or "").strip()
    source = str(url or "").strip()
    if not dest or not source:
        return 2
    folder = os.path.dirname(dest)
    if folder:
        os.makedirs(folder, exist_ok=True)
    try:
        urllib.request.urlretrieve(source, dest)
    except (OSError, urllib.error.URLError, ValueError):
        return 1
    return 0 if os.path.isfile(dest) else 1


def _cleanup(root: str) -> None:
    text = str(root or "").strip()
    if not text:
        return
    base = os.path.basename(text.rstrip("\\/"))
    if "jarvis-lan-add-" not in base:
        return
    shutil.rmtree(text, ignore_errors=True)


def _parse_fetch(spec: str) -> tuple[str, str] | None:
    text = str(spec or "").strip()
    if "=" not in text:
        return None
    url, path = text.rsplit("=", 1)
    url = url.strip()
    path = path.strip()
    if not url or not path:
        return None
    return url, path


_ACCEPT_MANIFEST = (
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.index.v1+json"
)
_INDEX_TYPES = {
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
}
_SSL = ssl._create_unverified_context()
_HOST_SCHEME: dict[str, str] = {}


def _docker_bin() -> str:
    return shutil.which("docker") or shutil.which("docker.exe") or "docker"


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _tagged_ref(repo: str) -> str:
    text = str(repo or "").strip()
    if text.lower().startswith("docker://"):
        text = text[9:]
    if "@" in text.split("/", 1)[-1]:
        return text
    leaf = text.rsplit("/", 1)[-1]
    if ":" in leaf:
        return text
    return f"{text}:latest"


def _split_image(image: str) -> tuple[str, str, str]:
    text = _tagged_ref(image)
    host, _, rest = text.partition("/")
    if not rest or ("." not in host and ":" not in host and host != "localhost"):
        return "", "", ""
    name = rest
    leaf = rest.rsplit("/", 1)[-1]
    if "@" in leaf:
        name, digest = rest.rsplit("@", 1)
        return host, name, digest
    if ":" in leaf:
        name, tag = rest.rsplit(":", 1)
        return host, name, tag
    return host, name, "latest"


def _auth_header(host: str) -> str:
    path = Path.home() / ".docker" / "config.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return ""
    auths = payload.get("auths") if isinstance(payload, dict) else None
    if not isinstance(auths, dict):
        return ""
    wanted = str(host or "").strip().lower()
    for key, row in auths.items():
        text = str(key or "").strip()
        stripped = text.replace("https://", "").replace("http://", "").split("/", 1)[0].lower()
        if stripped != wanted and text.lower() != wanted:
            continue
        if not isinstance(row, dict):
            continue
        auth = str(row.get("auth") or "").strip()
        if auth:
            return auth if auth.lower().startswith("basic ") else f"Basic {auth}"
        user = str(row.get("username") or "")
        if user:
            import base64

            token = base64.b64encode(f"{user}:{row.get('password') or ''}".encode()).decode("ascii")
            return f"Basic {token}"
    return ""


def _headers(host: str, accept: str = "") -> dict[str, str]:
    headers = {"User-Agent": "jarvis-lan-oci/1"}
    if accept:
        headers["Accept"] = accept
    auth = _auth_header(host)
    if auth:
        headers["Authorization"] = auth
    return headers


def _urlopen(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    return urllib.request.urlopen(req, context=_SSL, timeout=120)


def _probe_scheme(host: str, scheme: str) -> bool:
    try:
        resp = _urlopen(f"{scheme}://{host}/v2/", headers=_headers(host, "application/json"))
        resp.read(64)
        return True
    except urllib.error.HTTPError as exc:
        return int(exc.code) in {200, 401, 403}
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _scheme(host: str) -> str:
    cached = _HOST_SCHEME.get(host)
    if cached:
        return cached
    for scheme in ("https", "http"):
        if _probe_scheme(host, scheme):
            _HOST_SCHEME[host] = scheme
            return scheme
    _HOST_SCHEME[host] = "http"
    return "http"


def _registry_url(host: str, path: str) -> str:
    loc = path if str(path).startswith("/") else f"/{path}"
    return f"{_scheme(host)}://{host}{loc}"


def _registry_bytes(
    host: str,
    path: str,
    *,
    accept: str = "",
    data: bytes | None = None,
    method: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    headers = _headers(host, accept)
    if extra_headers:
        headers.update(extra_headers)
    resp = _urlopen(_registry_url(host, path), data=data, headers=headers, method=method)
    with resp:
        body = resp.read()
        ctype = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        return body, ctype


def _registry_json(host: str, path: str, *, accept: str = "") -> tuple[dict, str]:
    body, ctype = _registry_bytes(host, path, accept=accept or _ACCEPT_MANIFEST)
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("registry json")
    return payload, ctype


def _platform_from_extra(extra: list[str] | None) -> tuple[str, str, str]:
    os_name = "linux"
    arch = ""
    variant = ""
    items = list(extra or [])
    index = 0
    while index < len(items):
        flag = items[index]
        if flag == "--override-os" and index + 1 < len(items):
            os_name = items[index + 1]
            index += 2
            continue
        if flag == "--override-arch" and index + 1 < len(items):
            arch = items[index + 1]
            index += 2
            continue
        if flag == "--override-variant" and index + 1 < len(items):
            variant = items[index + 1]
            index += 2
            continue
        index += 1
    if not arch:
        machine = platform.machine().lower()
        arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
            machine, machine or "amd64"
        )
    return os_name, arch, variant


def _select_manifest(host: str, name: str, tag: str, extra: list[str] | None) -> dict:
    payload, ctype = _registry_json(host, f"/v2/{name}/manifests/{tag}", accept=_ACCEPT_MANIFEST)
    if ctype in _INDEX_TYPES or payload.get("manifests"):
        os_name, arch, variant = _platform_from_extra(extra)
        for item in payload.get("manifests") or []:
            if not isinstance(item, dict):
                continue
            plat = item.get("platform") if isinstance(item.get("platform"), dict) else {}
            if str(plat.get("os") or "") != os_name:
                continue
            if str(plat.get("architecture") or "") != arch:
                continue
            if variant and str(plat.get("variant") or "") != variant:
                continue
            digest = str(item.get("digest") or "")
            if not digest:
                continue
            chosen, _ctype = _registry_json(host, f"/v2/{name}/manifests/{digest}", accept=_ACCEPT_MANIFEST)
            return chosen
        raise ValueError("no matching platform manifest")
    return payload


def _blob(host: str, name: str, digest: str) -> bytes:
    body, _ctype = _registry_bytes(host, f"/v2/{name}/blobs/{digest}")
    if digest.startswith("sha256:") and _sha256(body) != digest:
        raise ValueError("blob digest mismatch")
    return body


def _gunzip_if_needed(data: bytes) -> bytes:
    if len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B:
        return gzip.decompress(data)
    return data


def _python_list_tags(image: str) -> list[str] | None:
    host, name, _tag = _split_image(_tagged_ref(image))
    if not host or not name:
        return None
    try:
        payload, _ctype = _registry_json(host, f"/v2/{name}/tags/list", accept="application/json")
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return None
    raw = payload.get("tags")
    if not isinstance(raw, list):
        return []
    return [f"{host}/{name}:{item}" for item in raw if str(item).strip() and "<none>" not in str(item)]


def _write_docker_archive(image: str, layers: list[bytes], config: bytes, dest: str) -> None:
    names = [f"layer{index}.tar" for index in range(len(layers))]
    payload = [{"Config": "config.json", "RepoTags": [image], "Layers": names}]
    with tarfile.open(dest, "w") as archive:

        def add_bytes(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

        add_bytes("manifest.json", json.dumps(payload).encode("utf-8"))
        add_bytes("config.json", config)
        for name, layer in zip(names, layers, strict=True):
            add_bytes(name, layer)


def _python_pull(image: str, extra: list[str] | None, quiet: bool) -> int:
    tagged = _tagged_ref(image)
    host, name, tag = _split_image(tagged)
    if not host or not name:
        return 1
    try:
        manifest = _select_manifest(host, name, tag, extra)
        config_spec = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        config_digest = str(config_spec.get("digest") or "")
        if not config_digest:
            return 1
        config = _blob(host, name, config_digest)
        layers: list[bytes] = []
        for item in manifest.get("layers") or []:
            if not isinstance(item, dict):
                return 1
            digest = str(item.get("digest") or "")
            if not digest:
                return 1
            layers.append(_gunzip_if_needed(_blob(host, name, digest)))
        load = tempfile.NamedTemporaryFile(prefix="jarvis-lan-oci-", suffix=".tar", delete=False)
        load.close()
        try:
            _write_docker_archive(tagged, layers, config, load.name)
            cmd = [_docker_bin(), "load", "-i", load.name]
            if quiet:
                cmd.append("-q")
            proc = subprocess.run(cmd, check=False)
            return int(proc.returncode or 0)
        finally:
            try:
                os.unlink(load.name)
            except OSError:
                pass
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, gzip.BadGzipFile, tarfile.TarError):
        return 1


def _gzip_bytes(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(data)
    return buf.getvalue()


def _upload_blob(host: str, name: str, digest: str, data: bytes) -> None:
    try:
        _registry_bytes(host, f"/v2/{name}/blobs/{digest}", method="HEAD")
        return
    except urllib.error.HTTPError as exc:
        if int(exc.code) not in {404, 405}:
            raise
    except (OSError, urllib.error.URLError):
        pass
    req = urllib.request.Request(
        _registry_url(host, f"/v2/{name}/blobs/uploads/"),
        data=b"",
        headers=_headers(host),
        method="POST",
    )
    resp = urllib.request.urlopen(req, context=_SSL, timeout=120)
    location = str(resp.headers.get("Location") or "")
    resp.read()
    if not location:
        raise ValueError("upload location")
    if location.startswith("/"):
        location = _registry_url(host, location)
    sep = "&" if "?" in location else "?"
    put = urllib.request.Request(
        f"{location}{sep}digest={digest}",
        data=data,
        headers={**_headers(host), "Content-Type": "application/octet-stream"},
        method="PUT",
    )
    urllib.request.urlopen(put, context=_SSL, timeout=120).read()


def _python_push(image: str, extra: list[str] | None, quiet: bool) -> int:
    del extra
    tagged = _tagged_ref(image)
    host, name, tag = _split_image(tagged)
    if not host or not name:
        return 1
    save = tempfile.NamedTemporaryFile(prefix="jarvis-lan-oci-save-", suffix=".tar", delete=False)
    save.close()
    extract = tempfile.mkdtemp(prefix="jarvis-lan-oci-")
    try:
        cmd = [_docker_bin(), "save", "-o", save.name, tagged]
        proc = subprocess.run(cmd, check=False)
        if proc.returncode:
            return int(proc.returncode)
        with tarfile.open(save.name, "r") as archive:
            archive.extractall(extract, filter="data")
        root = Path(extract)
        rows = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return 1
        row = rows[0]
        config_name = str(row.get("Config") or "")
        config = (root / config_name).read_bytes()
        config_digest = _sha256(config)
        _upload_blob(host, name, config_digest, config)
        layer_descs: list[dict] = []
        for layer_name in row.get("Layers") or []:
            raw = (root / str(layer_name)).read_bytes()
            gz = _gzip_bytes(raw)
            digest = _sha256(gz)
            _upload_blob(host, name, digest, gz)
            layer_descs.append(
                {
                    "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    "size": len(gz),
                    "digest": digest,
                }
            )
        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "size": len(config),
                "digest": config_digest,
            },
            "layers": layer_descs,
        }
        body = json.dumps(manifest).encode("utf-8")
        _registry_bytes(
            host,
            f"/v2/{name}/manifests/{tag}",
            data=body,
            method="PUT",
            extra_headers={"Content-Type": "application/vnd.docker.distribution.manifest.v2+json"},
        )
        return 0
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, tarfile.TarError, gzip.BadGzipFile):
        return 1
    finally:
        try:
            os.unlink(save.name)
        except OSError:
            pass
        shutil.rmtree(extract, ignore_errors=True)


def _python_copy(image: str, *, quiet: bool, push: bool, extra: list[str] | None = None) -> int:
    if push:
        return _python_push(image, extra, quiet)
    return _python_pull(image, extra, quiet)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    quiet = False
    push = False
    all_tags = False
    python_copy = False
    extra: list[str] = []
    push_after: list[str] = []
    fetches: list[tuple[str, str]] = []
    cleanup = ""
    while args:
        if args[0] in {"-q", "--quiet"}:
            quiet = True
            args = args[1:]
            continue
        if args[0] == "--push":
            push = True
            args = args[1:]
            continue
        if args[0] == "--python-copy":
            python_copy = True
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
        if args[0] == "--cleanup" and len(args) > 1:
            cleanup = args[1]
            args = args[2:]
            continue
        if args[0].startswith("--cleanup="):
            cleanup = args[0].split("=", 1)[1]
            args = args[1:]
            continue
        if args[0] == "--fetch" and len(args) > 1:
            parsed = _parse_fetch(args[1])
            if parsed is None:
                return 2
            fetches.append(parsed)
            args = args[2:]
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
    try:
        if python_copy:
            exe = ""
            images = list(args)
            if not images and not follow and not then and not fetches and not push_after:
                return 2
        elif not args:
            if not follow and not then and not fetches and not push_after:
                return 2
            exe = ""
            images = []
        else:
            exe, *images = args
            if not exe:
                return 2
        if all_tags:
            if not exe and not python_copy:
                return 1
            expanded: list[str] = []
            for image in images:
                tags = _expand_all_tags(exe, image, push=push)
                if tags is None:
                    return 1
                expanded.extend(tags)
            images = expanded
            if not images and not push_after and not fetches:
                return 1
        if python_copy:
            for image in images:
                code = _python_copy(image, quiet=quiet, push=push, extra=extra)
                if code:
                    return code
        elif exe:
            for image in images:
                code = _copy(exe, image, quiet=quiet, push=push, extra=extra)
                if code:
                    return code
        for url, outfile in fetches:
            code = _fetch(url, outfile)
            if code:
                return code
        if follow:
            proc = subprocess.run(follow, check=False)
            if proc.returncode:
                return int(proc.returncode)
        if python_copy:
            for image in push_after:
                code = _python_copy(image, quiet=quiet, push=True, extra=extra)
                if code:
                    return code
        elif exe:
            for image in push_after:
                code = _copy(exe, image, quiet=quiet, push=True, extra=extra)
                if code:
                    return code
        elif push_after:
            return 2
        if then:
            proc = subprocess.run(then, check=False)
            if proc.returncode:
                return int(proc.returncode)
        return 0
    finally:
        _cleanup(cleanup)


if __name__ == "__main__":
    raise SystemExit(main())
