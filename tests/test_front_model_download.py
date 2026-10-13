"""Behavioural tests for installer/windows/front-model-download.ps1 (PR #615).

A local HTTP server simulates interrupted transfers, Range resume, servers that
ignore Range, and corrupt bodies. The PowerShell helper is dot-sourced and run
for real, so these tests exercise the code the autobuild uses.
"""

from __future__ import annotations

import hashlib
import http.server
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "installer" / "windows" / "front-model-download.ps1"
STAGE = REPO_ROOT / "installer" / "windows" / "stage-front-model.ps1"
PAYLOAD = os.urandom(3 * 1024 * 1024 + 12345)
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _shell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


class _Server:
    """Scripted server: each request pops the next behaviour from ``plan``."""

    def __init__(self, plan: list[str]):
        self.plan = list(plan)
        self.requests: list[str | None] = []
        self.bytes_sent = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # pragma: no cover - quiet
                pass

            def do_GET(self):  # noqa: N802
                rng = self.headers.get("Range")
                outer.requests.append(rng)
                mode = outer.plan.pop(0) if outer.plan else "ok"
                start = 0
                if rng and mode != "ignore_range":
                    start = int(rng.split("=", 1)[1].split("-", 1)[0])
                body = PAYLOAD[start:]
                if mode == "corrupt":
                    body = bytes(len(body))
                if mode == "fail500":
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if start:
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                if mode == "drop":
                    chunk = body[: len(body) * 2 // 5]
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    outer.bytes_sent += len(chunk)
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                self.wfile.write(body)
                outer.bytes_sent += len(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/model.gguf"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _run(server: _Server, dest: Path, attempts: int = 3) -> subprocess.CompletedProcess:
    shell = _shell()
    script = (
        f". '{HELPER}'; "
        f"Invoke-FrontResumableDownload -Url '{server.url}' -Destination '{dest}' "
        f"-ExpectedBytes {len(PAYLOAD)} -ExpectedSha '{SHA}' -Attempts {attempts} "
        "-BackoffSeconds 0 -TimeoutSeconds 10"
    )
    return subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=180,
    )


pytestmark = pytest.mark.skipif(_shell() is None, reason="PowerShell is not installed")


@pytest.fixture
def serve():
    servers: list[_Server] = []

    def make(plan):
        s = _Server(plan)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def test_interrupted_download_resumes_with_range(serve, tmp_path):
    server = serve(["drop", "ok"])
    dest = tmp_path / "model.gguf"
    res = _run(server, dest)
    assert res.returncode == 0, res.stdout + res.stderr
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == SHA
    assert server.requests[0] is None
    assert server.requests[1] and server.requests[1].startswith("bytes=")
    assert int(server.requests[1].split("=")[1].rstrip("-")) > 0
    # Resume fetched only the missing bytes, not the whole file again.
    assert server.bytes_sent == len(PAYLOAD)
    assert not (tmp_path / "model.gguf.part").exists()


def test_partial_from_previous_run_is_resumed(serve, tmp_path):
    dest = tmp_path / "model.gguf"
    (tmp_path / "model.gguf.part").write_bytes(PAYLOAD[:1_000_000])
    server = serve(["ok"])
    res = _run(server, dest)
    assert res.returncode == 0, res.stdout + res.stderr
    assert server.requests == ["bytes=1000000-"]
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == SHA


def test_server_ignoring_range_restarts_cleanly(serve, tmp_path):
    dest = tmp_path / "model.gguf"
    (tmp_path / "model.gguf.part").write_bytes(PAYLOAD[:500_000])
    server = serve(["ignore_range"])
    res = _run(server, dest)
    assert res.returncode == 0, res.stdout + res.stderr
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == SHA


def test_hash_mismatch_deletes_file_and_retries_from_zero(serve, tmp_path):
    server = serve(["corrupt", "ok"])
    dest = tmp_path / "model.gguf"
    res = _run(server, dest)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "SHA-256 mismatch" in res.stdout + res.stderr
    assert server.requests == [None, None]
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == SHA


def test_final_failure_removes_partial_and_reports_every_attempt(serve, tmp_path):
    server = serve(["drop", "fail500", "fail500"])
    dest = tmp_path / "model.gguf"
    res = _run(server, dest, attempts=3)
    assert res.returncode != 0
    out = res.stdout + res.stderr
    assert "failed after 3 attempts" in out
    assert "HTTP 500" in out
    assert not dest.exists()
    assert not (tmp_path / "model.gguf.part").exists()


def test_stage_script_keeps_partials_and_writes_no_temp_logs():
    stage = STAGE.read_text(encoding="utf-8-sig")
    helper = HELPER.read_text(encoding="utf-8-sig")
    assert "front-model-download.ps1" in stage
    assert "Invoke-FrontResumableDownload" in stage
    assert "Clear-FrontDownloadPartials" not in stage
    assert "jarvis-front-model-hf" not in stage
    assert "$env:TEMP" not in stage and "$env:TEMP" not in helper
    assert "RangeHeaderValue" in helper
