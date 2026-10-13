"""RFC-0198 LTA protected-folder unlock — backend unit tests (synthetic keys only)."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtensionOID, NameOID
from fastapi.testclient import TestClient

from app.agent.planning import (
    is_defensive_operator_prompt,
    lta_protected_folder_path,
    route_request,
)
from app.agent.tool_exposure import tool_names_for
from app.main import app
from app.security.lta_archive import (
    THEMIS_PERSONA_HINT,
    parse_manifest_access,
    run_protected_folder_open,
    start_protected_folder_open,
)
from app.security.lta_certs import (
    list_cert_candidates,
    normalize_hex_id,
    register_recovery_key_metadata,
    resolve_key_for_access,
    scrub_secret_fields,
    set_test_key_resolver,
)
from app.security.lta_errors import LTA_ERROR_CODES, PathDenied
from app.security.security_agents import mode_tools
from app.security.security_audit import audit_path, read_audit_lines


def _make_synthetic_identity(tmp: Path) -> dict[str, object]:
    """Generate RSA key + self-signed cert in temp dir only (never committed)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ski = hashes.Hash(hashes.SHA1())
    # Stable-ish SKI from public key bytes for matching
    pub_der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    ski.update(pub_der)
    ski_bytes = ski.finalize()[:20]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "lta-synthetic-test")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "lta-synthetic-test")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.SubjectKeyIdentifier(ski_bytes), critical=False)
        .sign(key, hashes.SHA256())
    )
    thumb = cert.fingerprint(hashes.SHA1()).hex().upper()
    ski_hex = ski_bytes.hex().upper()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    tmp.mkdir(parents=True, exist_ok=True)
    key_path = tmp / "synthetic-key.pem"
    cert_path = tmp / "synthetic-cert.pem"
    key_path.write_bytes(key_pem)
    cert_path.write_bytes(cert_pem)
    return {
        "thumbprint": thumb,
        "ski": ski_hex,
        "key_pem": key_pem,
        "cert_pem": cert_pem,
        "key_path": key_path,
        "cert_path": cert_path,
    }


def _cms_encrypt_password(password: str, cert_path: Path, out_dir: Path, *, encoding: str = "utf-8") -> str:
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("OpenSSL CLI is required for the synthetic CMS integration fixture")
    plain = out_dir / "plain-password.bin"
    cms = out_dir / "access.p7"
    plain.write_bytes(password.encode(encoding))
    subprocess.check_call(
        [
            openssl,
            "cms",
            "-encrypt",
            "-aes256",
            "-outform",
            "DER",
            "-in",
            str(plain),
            "-out",
            str(cms),
            "-recip",
            str(cert_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return base64.b64encode(cms.read_bytes()).decode("ascii")


def _build_bundle(
    tmp: Path, *, password: str = "synth-archive-pass-0198", plaintext_encoding: str = "utf-8"
) -> dict[str, object]:
    identity = _make_synthetic_identity(tmp / "keys")
    work = tmp / "bundle"
    work.mkdir(parents=True, exist_ok=True)
    access_b64 = _cms_encrypt_password(  # type: ignore[arg-type]
        password, identity["cert_path"], work, encoding=plaintext_encoding
    )
    thumb = identity["thumbprint"]
    ski = identity["ski"]
    # Placeholder shape only — ciphertext is synthetic for this temp dir.
    manifest = work / "manifest.xml"
    manifest.write_text(
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<LtaManifest>\n"
        f'  <Access CertThumbprint="{thumb}" SubjectKeyIdentifier="{ski}">'
        f"{access_b64}</Access>\n"
        "</LtaManifest>\n",
        encoding="utf-8",
    )
    payload = work / "payload"
    payload.mkdir()
    (payload / "evidence.txt").write_text("authorized-recovery-fixture\n", encoding="utf-8")
    archive = work / "archive.7z"
    archive_tool = shutil.which("7z") or os.environ.get("JARVIS_7Z_PATH")
    if not archive_tool or not Path(archive_tool).is_file():
        pytest.skip("7-Zip CLI is required for the encrypted archive integration fixture")
    subprocess.check_call(
        [
            archive_tool,
            "a",
            f"-p{password}",
            "-mhe=on",
            str(archive),
            str(payload / "evidence.txt"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        **identity,
        "password": password,
        "manifest_path": manifest,
        "archive_path": archive,
        "work": work,
        "access_b64": access_b64,
    }


@pytest.fixture
def lta_env(jarvis_env, monkeypatch):
    tmp: Path = jarvis_env["tmp"]
    monkeypatch.setattr("app.security.lta_archive.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.lta_certs.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.security_audit.data_dir", lambda: tmp)
    monkeypatch.setattr("app.security.lta_archive.load_settings", lambda: jarvis_env["settings"])
    set_test_key_resolver(None)
    yield {"tmp": tmp, "settings": jarvis_env["settings"]}
    set_test_key_resolver(None)


def test_error_taxonomy_codes_stable():
    assert "manifest_not_found" in LTA_ERROR_CODES
    assert "path_denied" in LTA_ERROR_CODES
    assert "decrypt_failed" in LTA_ERROR_CODES
    assert "archive_failed" in LTA_ERROR_CODES


def test_planner_hook_extracts_path():
    path = lta_protected_folder_path(r"Open this protected folder: D:\Evidence\Case-42\manifest.xml")
    assert path and path.endswith("manifest.xml")
    path2 = lta_protected_folder_path("unlock the LTA archive at /tmp/owner/bundle")
    assert path2 == "/tmp/owner/bundle"
    assert lta_protected_folder_path("hello there") is None
    # Must not accept PEM paste as a path
    assert (
        lta_protected_folder_path(
            "open this protected folder: -----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----"
        )
        is None
    )


def test_defensive_prompt_and_route_include_lta():
    text = "Open this protected folder: /tmp/case/manifest.xml"
    assert is_defensive_operator_prompt(text)
    route = route_request(text)
    assert route.kind == "managed_task"
    assert "lta_protected_folder" in mode_tools("blue")
    names = tool_names_for("mixed", prompt=text, security_role="blue-team")
    assert "lta_protected_folder" in names


def test_cert_candidates_no_private_key_export(lta_env):
    payload = list_cert_candidates()
    assert payload["private_key_export"] is False
    assert payload["persona_bind_hint"]["primary_persona_id"] == "themis"
    assert payload["persona_bind_hint"]["presence_shape_hint"] == "twin_shield"
    dumped = json.dumps(payload)
    assert "PRIVATE KEY" not in dumped
    assert "BEGIN " not in dumped


def test_scrub_secret_fields():
    cleaned = scrub_secret_fields(
        {
            "job_id": "abc",
            "password": "secret",
            "private_key_pem": "BEGIN",
            "nested": {"archive_password": "x", "ok": 1},
        }
    )
    assert "password" not in cleaned
    assert "private_key_pem" not in cleaned
    assert cleaned["nested"]["ok"] == 1
    assert "archive_password" not in cleaned["nested"]


def test_path_denied_outside_allowed(lta_env):
    outside = Path("/etc/passwd")
    with pytest.raises(PathDenied) as exc:
        start_protected_folder_open(manifest_path=str(outside), sync=True)
    assert exc.value.code == "path_denied"


def test_manifest_parse_and_roundtrip_unlock(lta_env):
    bundle = _build_bundle(lta_env["tmp"] / "case1")
    thumb = str(bundle["thumbprint"])
    ski = str(bundle["ski"])
    key_pem = bundle["key_pem"]
    assert isinstance(key_pem, bytes)

    def _resolver(want_thumb: str | None, want_ski: str | None) -> bytes | None:
        if want_thumb and normalize_hex_id(want_thumb) == thumb:
            return key_pem
        if want_ski and normalize_hex_id(want_ski) == ski:
            return key_pem
        return None

    set_test_key_resolver(_resolver)
    entries = parse_manifest_access(bundle["manifest_path"])  # type: ignore[arg-type]
    assert len(entries) == 1
    assert entries[0].thumbprint == thumb

    job = run_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(bundle["archive_path"]),
    )
    assert job["status"] == "succeeded"
    assert job["error"] == ""
    assert job["cert_thumbprint_used"] == thumb
    assert any(name.endswith("evidence.txt") for name in job["extract_listing"])
    assert job["persona_bind_hint"]["primary_persona_id"] == THEMIS_PERSONA_HINT["primary_persona_id"]
    # No secret leakage in job or audit
    dumped = json.dumps(job)
    assert str(bundle["password"]) not in dumped
    assert "PRIVATE KEY" not in dumped
    assert bundle["access_b64"] not in dumped
    lines = read_audit_lines(limit=50)
    assert any(row.get("event") == "lta.open_succeeded" for row in lines)
    audit_text = audit_path().read_text(encoding="utf-8")
    assert str(bundle["password"]) not in audit_text
    assert "PRIVATE KEY" not in audit_text
    assert bundle["access_b64"] not in audit_text


def test_recovery_keys_vault_metadata(lta_env):
    bundle = _build_bundle(lta_env["tmp"] / "case2")
    # Copy key into recovery-keys and register metadata (no API PEM paste)
    from app.security.lta_certs import recovery_keys_root

    dest = recovery_keys_root() / "owner-recovery.pem"
    dest.write_bytes(bundle["key_pem"])  # type: ignore[arg-type]
    meta = register_recovery_key_metadata(
        thumbprint=str(bundle["thumbprint"]),
        subject_key_identifier=str(bundle["ski"]),
        label="synthetic-recovery",
        key_file="owner-recovery.pem",
    )
    assert meta["source"] == "recovery_keys"
    candidates = list_cert_candidates()
    assert any(c.get("thumbprint") == bundle["thumbprint"] for c in candidates["candidates"])
    resolved = resolve_key_for_access(
        thumbprint=str(bundle["thumbprint"]),
        subject_key_identifier=None,
    )
    assert resolved.source == "recovery_keys"
    assert resolved.private_key_pem is not None

    job = run_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(bundle["archive_path"]),
    )
    assert job["status"] == "succeeded"
    assert job["cert_source"] == "recovery_keys"


def test_cert_not_found_honest_error(lta_env):
    bundle = _build_bundle(lta_env["tmp"] / "case3")
    set_test_key_resolver(lambda *_: None)
    job = run_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(bundle["archive_path"]),
    )
    assert job["status"] == "failed"
    assert job["error"] == "cert_not_found"


def test_wrong_key_decrypt_failed(lta_env):
    bundle = _build_bundle(lta_env["tmp"] / "case4")
    other = _make_synthetic_identity(lta_env["tmp"] / "other-key")

    def _wrong(_t: str | None, _s: str | None) -> bytes | None:
        return other["key_pem"]  # type: ignore[return-value]

    set_test_key_resolver(_wrong)
    job = run_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(bundle["archive_path"]),
    )
    assert job["status"] == "failed"
    assert job["error"] == "decrypt_failed"


_GARBAGE_PLAINTEXTS = (
    bytes.fromhex("9cff10d800fe81a7c4e2593b0d6f11e8"),
    bytes.fromhex("d800dc41c0afe3b1009f7a5512ee86fd"),
    bytes.fromhex("4e8a61e7f3d2a1009b7c0e1f88deadbe"),
    bytes.fromhex("e4b8ade696870000d83dde00ffeeddcc"),
)


@pytest.mark.parametrize("garbage", _GARBAGE_PLAINTEXTS, ids=lambda g: g.hex()[:8])
def test_wrong_key_garbage_plaintext_is_decrypt_failed(lta_env, monkeypatch, garbage):
    """Regression: a wrong RSA key could "decrypt" CMS to random bytes (~1 in 256 CBC
    paddings pass). Those bytes must classify as decrypt_failed, never archive_failed."""
    import app.security.lta_archive as lta_archive

    bundle = _build_bundle(lta_env["tmp"] / "case-garbage")
    other = _make_synthetic_identity(lta_env["tmp"] / "other-key-garbage")
    set_test_key_resolver(lambda _t, _s: other["key_pem"])  # type: ignore[arg-type,return-value]
    real_run = subprocess.run
    seen: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        if len(argv) > 2 and argv[1:3] == ["cms", "-decrypt"]:
            seen.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout=garbage, stderr=b"")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(lta_archive.subprocess, "run", fake_run)
    job = run_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(bundle["archive_path"]),
    )
    assert seen, "CMS decrypt was not invoked"
    assert job["status"] == "failed"
    assert job["error"] == "decrypt_failed"


def test_real_wrong_key_cms_decrypt_always_fails(tmp_path):
    """Real OpenSSL: without -debug_decrypt about 1 in 256 wrong keys 'succeeded' with
    garbage (1200 tries catch that regression with ~99% probability). Every wrong-key
    decrypt must raise DecryptFailed."""
    from app.security.lta_archive import _decrypt_openssl_cms
    from app.security.lta_errors import DecryptFailed

    right = _make_synthetic_identity(tmp_path / "right")
    wrong = _make_synthetic_identity(tmp_path / "wrong")
    for index in range(1200):
        work = tmp_path / f"w{index}"
        work.mkdir()
        blob = base64.b64decode(_cms_encrypt_password("S3cret-pass_123", right["cert_path"], work))  # type: ignore[arg-type]
        with pytest.raises(DecryptFailed):
            _decrypt_openssl_cms(blob, wrong["key_pem"])  # type: ignore[arg-type]
        shutil.rmtree(work)


def test_openssl_cms_decrypt_passes_debug_decrypt(tmp_path, monkeypatch):
    """Deterministic: the OpenSSL CMS command always carries -debug_decrypt."""
    import app.security.lta_archive as lta_archive

    seen: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=b"S3cret-pass", stderr=b"")

    monkeypatch.setattr(lta_archive.subprocess, "run", fake_run)
    monkeypatch.setattr(lta_archive.shutil, "which", lambda _name: "/usr/bin/openssl")
    assert lta_archive._decrypt_openssl_cms(b"blob", b"-----BEGIN PRIVATE KEY-----") == "S3cret-pass"
    assert len(seen) == 1
    assert seen[0][1:3] == ["cms", "-decrypt"]
    assert "-debug_decrypt" in seen[0]


def test_decode_cms_password_mapping():
    from app.security.lta_archive import _decode_cms_password
    from app.security.lta_errors import DecryptFailed

    assert _decode_cms_password(b"S3cret-pass") == "S3cret-pass"
    assert _decode_cms_password("S3cret-pässwörd".encode("utf-16-le")) == "S3cret-pässwörd"
    assert _decode_cms_password("S3cret".encode("utf-16-le") + b"\x00\x00") == "S3cret"
    assert _decode_cms_password("证据密码".encode("utf-16-le")) == "证据密码"
    assert _decode_cms_password("пароль".encode("utf-8")) == "пароль"
    assert _decode_cms_password(b"\x00\x00") == ""
    # Format characters (Cf) such as ZWJ are legitimate password content.
    assert _decode_cms_password("pass\u200dword".encode("utf-16-le")) == "pass\u200dword"
    assert _decode_cms_password("pass\u200dword".encode("utf-8")) == "pass\u200dword"
    # A leading BOM is stripped exactly once.
    assert _decode_cms_password(b"\xff\xfe" + "S3cret-wide".encode("utf-16-le")) == "S3cret-wide"
    assert _decode_cms_password("\ufeffS3cret".encode("utf-8")) == "S3cret"
    bad = (
        b"\xd8\x00\xd8",  # odd length, not UTF-8
        b"\x00\xd8A\x00",  # unpaired surrogate
        b"pass\x07word",  # control character
        b"a\x00b",  # embedded NUL, odd length
        "pass\ue000".encode("utf-16-le"),  # private use
        "pass\u2028word".encode("utf-16-le"),  # line separator (Zl)
        "pass\u2029word".encode("utf-16-le"),  # paragraph separator (Zp)
        "pass\u0378".encode("utf-16-le"),  # unassigned
    )
    for raw in bad:
        with pytest.raises(DecryptFailed):
            _decode_cms_password(raw)


def test_cjk_utf16_password_opens_real_archive(lta_env):
    password = "证据密码二〇二六"
    bundle = _build_bundle(lta_env["tmp"] / "case-cjk", password=password, plaintext_encoding="utf-16-le")
    key_pem = bundle["key_pem"]
    set_test_key_resolver(lambda _t, _s: key_pem)  # type: ignore[arg-type,return-value]
    job = run_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(bundle["archive_path"]),
    )
    assert job["status"] == "succeeded", job
    assert job["error"] == ""


def test_7z_failure_classification():
    from app.security.lta_archive import _is_7z_encrypted_data_error, _is_7z_wrong_password

    assert _is_7z_wrong_password(b"", b"ERROR: a.7z\nCannot open encrypted archive. Wrong password?\nHeaders Error")
    # Per-file encrypted errors appear for corrupt data even with the right password.
    for msg in (
        b"ERROR: Data Error in encrypted file. Wrong password? : f.txt",
        b"ERROR: CRC Failed in encrypted file. Wrong password? : f.txt",
    ):
        assert not _is_7z_wrong_password(b"", msg)
        assert _is_7z_encrypted_data_error(b"", msg)
    assert not _is_7z_wrong_password(b"", b"ERROR: x.7z\nCannot open the file as archive")
    assert not _is_7z_encrypted_data_error(b"", b"ERROR: x.7z\nCannot open the file as archive")
    assert not _is_7z_wrong_password(b"", b"ERROR: Disk full")


def test_correct_key_corrupt_7z_data_is_archive_failed(lta_env):
    """Right key + corrupted encrypted 7z payload must be archive_failed, never decrypt_failed."""
    bundle = _build_bundle(lta_env["tmp"] / "case-corrupt")
    archive = Path(bundle["archive_path"])  # type: ignore[arg-type]
    data = bytearray(archive.read_bytes())
    # Packed (encrypted) stream starts right after the 32-byte signature header.
    for off in range(32, min(48, len(data))):
        data[off] ^= 0xFF
    archive.write_bytes(bytes(data))
    key_pem = bundle["key_pem"]
    set_test_key_resolver(lambda _t, _s: key_pem)  # type: ignore[arg-type,return-value]
    job = run_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(archive),
    )
    assert job["status"] == "failed", job
    assert job["error"] == "archive_failed", job
    assert job["error_detail"] == "7z_encrypted_data_error", job


def test_7z_non_archive_is_archive_failed(lta_env):
    from app.security.lta_archive import extract_with_7z
    from app.security.lta_errors import ArchiveFailed, DecryptFailed

    if not shutil.which("7z"):
        pytest.skip("7-Zip CLI is required")
    bogus = lta_env["tmp"] / "not-an-archive.7z"
    bogus.write_bytes(b"this is not a 7z archive" * 8)
    with pytest.raises(ArchiveFailed) as caught:
        extract_with_7z(bogus, "any-password", lta_env["tmp"] / "lta-extract" / "bogus")
    assert not isinstance(caught.value, DecryptFailed)


def test_random_wrong_key_plaintexts_end_in_decrypt_failed(lta_env):
    """Property: random 16-byte non-UTF-8 wrong-key plaintexts never open the archive.

    Strict UTF-16-LE accepts any script (RFC-0198 passwords may be non-Latin), so about a
    quarter of random buffers decode to plausible text. Those go to 7-Zip, which rejects
    them as a wrong password; the rest are rejected at decode. Either way: decrypt_failed.
    """
    import random

    from app.security.lta_archive import _decode_cms_password, extract_with_7z
    from app.security.lta_errors import DecryptFailed

    bundle = _build_bundle(lta_env["tmp"] / "case-property")
    rng = random.Random(0x0198)
    tried = rejected_at_decode = rejected_by_7z = 0
    while tried < 2_000:
        raw = bytes(rng.getrandbits(8) for _ in range(16))
        try:
            raw.decode("utf-8")
            continue
        except UnicodeDecodeError:
            pass
        tried += 1
        try:
            password = _decode_cms_password(raw)
        except DecryptFailed:
            rejected_at_decode += 1
            continue
        assert password
        with pytest.raises(DecryptFailed):
            extract_with_7z(bundle["archive_path"], password, lta_env["tmp"] / "lta-extract" / f"p{tried}")  # type: ignore[arg-type]
        rejected_by_7z += 1
    assert rejected_at_decode + rejected_by_7z == tried
    assert rejected_at_decode > tried // 2


def test_xml_invalid(lta_env):
    bad = lta_env["tmp"] / "bad.xml"
    bad.write_text("<not-closed", encoding="utf-8")
    job = run_protected_folder_open(manifest_path=str(bad))
    assert job["status"] == "failed"
    assert job["error"] == "xml_invalid"


def test_api_open_status_certs(lta_env, allow_loopback_api):
    bundle = _build_bundle(lta_env["tmp"] / "case-api")
    thumb = str(bundle["thumbprint"])
    key_pem = bundle["key_pem"]
    assert isinstance(key_pem, bytes)
    set_test_key_resolver(
        lambda t, s: key_pem if (t == thumb or s == bundle["ski"]) else None
    )
    client = TestClient(app)
    opened = client.post(
        "/api/lta/protected-folder/open",
        json={
            "manifest_path": str(bundle["manifest_path"]),
            "archive_path": str(bundle["archive_path"]),
            "sync": True,
        },
    )
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["status"] == "succeeded"
    assert body["persona_bind_hint"]["primary_persona_id"] == "themis"
    job_id = body["id"]
    status = client.get(f"/api/lta/jobs/{job_id}")
    assert status.status_code == 200
    detail = status.json()
    assert detail["status"] == "succeeded"
    assert any("evidence.txt" in name for name in detail["extract_listing"])
    certs = client.get("/api/lta/certs/candidates")
    assert certs.status_code == 200
    cert_body = certs.json()
    assert cert_body["private_key_export"] is False
    assert "PRIVATE KEY" not in certs.text


def test_api_path_denied(lta_env, allow_loopback_api):
    client = TestClient(app)
    resp = client.post(
        "/api/lta/protected-folder/open",
        json={"manifest_path": "/etc/passwd", "sync": True},
    )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["error"] == "path_denied"


def test_async_job_completes(lta_env):
    bundle = _build_bundle(lta_env["tmp"] / "case-async")
    thumb = str(bundle["thumbprint"])
    key_pem = bundle["key_pem"]
    assert isinstance(key_pem, bytes)
    set_test_key_resolver(lambda t, s: key_pem if t == thumb or s == bundle["ski"] else None)
    started = start_protected_folder_open(
        manifest_path=str(bundle["manifest_path"]),
        archive_path=str(bundle["archive_path"]),
        sync=False,
    )
    assert started["status"] == "queued"
    job_id = started["job_id"]
    deadline = time.time() + 15
    final = None
    while time.time() < deadline:
        from app.security.lta_archive import get_lta_job

        final = get_lta_job(job_id)
        if final["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert final is not None
    assert final["status"] == "succeeded"


def test_tool_registered():
    from app.tools.registry import REGISTRY

    assert "lta_protected_folder" in REGISTRY.tools
