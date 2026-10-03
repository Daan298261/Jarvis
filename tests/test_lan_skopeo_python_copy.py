"""OCI python-copy fallback when skopeo is missing (LAN HTTP proxy path)."""
from __future__ import annotations

import gzip
import hashlib
import http.server
import io
import json
import tarfile
import threading
from pathlib import Path

import pytest

from app.tools import lan_skopeo_load as helper


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _gzip(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(data)
    return buf.getvalue()


def _layer_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        info = tarfile.TarInfo("hello")
        payload = b"lan\n"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


class _Registry(http.server.BaseHTTPRequestHandler):
    blobs: dict[str, bytes] = {}
    manifests: dict[str, bytes] = {}
    uploads: dict[str, bytes] = {}
    put_manifests: dict[str, bytes] = {}

    def log_message(self, *_args):
        return

    def _send(self, code: int, body: bytes = b"", content_type: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self._handle_read()

    def do_HEAD(self):
        self._handle_read()

    def _handle_read(self):
        path = self.path.split("?", 1)[0]
        if path in {"/v2/", "/v2"}:
            self._send(200, b"{}")
            return
        if path.endswith("/tags/list"):
            self._send(200, json.dumps({"tags": ["latest", "v1"]}).encode())
            return
        if "/manifests/" in path:
            digest = path.rsplit("/", 1)[-1]
            body = self.manifests.get(digest) or self.manifests.get("latest")
            if body is None:
                self._send(404, b"{}")
                return
            self._send(200, body, "application/vnd.docker.distribution.manifest.v2+json")
            return
        if "/blobs/" in path:
            digest = path.rsplit("/", 1)[-1]
            body = self.blobs.get(digest)
            if body is None:
                self._send(404, b"")
                return
            self._send(200, body, "application/octet-stream")
            return
        self._send(404, b"")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path.endswith("/blobs/uploads/"):
            self.send_response(202)
            self.send_header("Location", "/v2/app/blobs/uploads/1")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(404, b"")

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        path, _, query = self.path.partition("?")
        if "/blobs/uploads/" in path:
            digest = ""
            for part in query.split("&"):
                if part.startswith("digest="):
                    digest = part.split("=", 1)[1]
            if digest:
                self.blobs[digest] = body
                self.uploads[digest] = body
            self._send(201, b"")
            return
        if "/manifests/" in path:
            tag = path.rsplit("/", 1)[-1]
            self.put_manifests[tag] = body
            self._send(201, b"")
            return
        self._send(404, b"")


@pytest.fixture
def registry():
    helper._HOST_SCHEME.clear()
    _Registry.blobs = {}
    _Registry.manifests = {}
    _Registry.uploads = {}
    _Registry.put_manifests = {}
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Registry)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = f"127.0.0.1:{server.server_address[1]}"
    yield host
    server.shutdown()
    thread.join(timeout=2)


def test_python_pull_loads_docker_archive(registry, tmp_path, monkeypatch):
    layer = _layer_tar()
    gz = _gzip(layer)
    config = json.dumps({"architecture": "amd64", "os": "linux"}).encode()
    layer_digest = _sha(gz)
    config_digest = _sha(config)
    _Registry.blobs = {layer_digest: gz, config_digest: config}
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {
            "mediaType": "application/vnd.docker.container.image.v1+json",
            "size": len(config),
            "digest": config_digest,
        },
        "layers": [
            {
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                "size": len(gz),
                "digest": layer_digest,
            }
        ],
    }
    _Registry.manifests = {"latest": json.dumps(manifest).encode()}
    loaded: list[str] = []

    def fake_run(cmd, check=False):
        if cmd[:2] == ["docker", "load"]:
            src = Path(cmd[cmd.index("-i") + 1])
            dest = tmp_path / "loaded.tar"
            dest.write_bytes(src.read_bytes())
            loaded.append(str(dest))
            return type("P", (), {"returncode": 0})()
        raise AssertionError(cmd)

    monkeypatch.setattr(helper, "_docker_bin", lambda: "docker")
    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    image = f"{registry}/app:latest"
    assert helper._python_copy(image, quiet=True, push=False) == 0
    assert loaded
    with tarfile.open(loaded[0], "r") as archive:
        names = set(archive.getnames())
        assert "manifest.json" in names
        assert "config.json" in names
        assert "layer0.tar" in names
        assert archive.extractfile("layer0.tar").read() == layer


def test_python_push_uploads_blobs_and_manifest(registry, tmp_path, monkeypatch):
    layer = _layer_tar()
    config = json.dumps({"architecture": "amd64", "os": "linux"}).encode()
    save = tmp_path / "save.tar"
    with tarfile.open(save, "w") as archive:

        def add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

        add(
            "manifest.json",
            json.dumps([{"Config": "config.json", "RepoTags": [f"{registry}/app:v1"], "Layers": ["layer0.tar"]}]).encode(),
        )
        add("config.json", config)
        add("layer0.tar", layer)

    def fake_run(cmd, check=False):
        if cmd[:2] == ["docker", "save"]:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(save.read_bytes())
            return type("P", (), {"returncode": 0})()
        raise AssertionError(cmd)

    monkeypatch.setattr(helper, "_docker_bin", lambda: "docker")
    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    image = f"{registry}/app:v1"
    assert helper._python_copy(image, quiet=False, push=True) == 0
    assert _Registry.put_manifests.get("v1")
    payload = json.loads(_Registry.put_manifests["v1"])
    assert payload["schemaVersion"] == 2
    assert payload["config"]["digest"].startswith("sha256:")
    assert payload["layers"][0]["digest"] in _Registry.uploads


def test_python_list_tags(registry):
    tags = helper._python_list_tags(f"{registry}/app")
    assert f"{registry}/app:latest" in tags
    assert f"{registry}/app:v1" in tags
