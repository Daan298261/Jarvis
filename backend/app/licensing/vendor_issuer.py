"""Vendor issuer SQLite store (RFC-0087).

Customer table lives in %LOCALAPPDATA%\\Jarvis\\license-issuer\\ so rebuilding
installer/windows/dist does not wipe licensees. Signing private key stays here
and is never copied into the Inno customer payload.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .. import __version__ as JARVIS_VERSION
from ..policy.cyber_ato import AtoError, issue_license
from .modules import catalog_rows, normalize_module_id, requires_law_enforcement
from .seal import product_seal_public_hex, seal_bytes

SCHEMA_VERSION = 1


def issuer_data_dir() -> Path:
    override = (os.environ.get("JARVIS_LICENSE_ISSUER_DIR") or "").strip()
    if override:
        path = Path(override)
    else:
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            path = Path(local) / "Jarvis" / "license-issuer"
        else:
            path = Path.home() / ".jarvis" / "license-issuer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def issuer_db_path() -> Path:
    return issuer_data_dir() / "issuer.sqlite"


def vendor_private_path() -> Path:
    return issuer_data_dir() / "issuer.key"


def vendor_public_path() -> Path:
    return issuer_data_dir() / "issuer.pub"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    text = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return text.replace("+00:00", "Z")


def load_or_create_vendor_keys() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    private_path = vendor_private_path()
    public_path = vendor_public_path()
    if private_path.is_file() and public_path.is_file():
        private = Ed25519PrivateKey.from_private_bytes(private_path.read_bytes())
        public = Ed25519PublicKey.from_public_bytes(public_path.read_bytes())
        return private, public
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    tmp_private = private_path.with_suffix(private_path.suffix + ".tmp")
    tmp_public = public_path.with_suffix(public_path.suffix + ".tmp")
    tmp_private.write_bytes(private.private_bytes_raw())
    tmp_public.write_bytes(public.public_bytes_raw())
    try:
        os.chmod(tmp_private, 0o600)
    except OSError:
        pass
    os.replace(tmp_private, private_path)
    os.replace(tmp_public, public_path)
    return private, public


def vendor_public_hex() -> str:
    _private, public = load_or_create_vendor_keys()
    return public.public_bytes_raw().hex()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(issuer_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS modules (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                requires_le INTEGER NOT NULL DEFAULT 0,
                kind TEXT NOT NULL DEFAULT 'runtime'
            );
            CREATE TABLE IF NOT EXISTS licensees (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS licenses (
                license_id TEXT PRIMARY KEY,
                licensee_id TEXT NOT NULL,
                jarvis_version TEXT NOT NULL,
                law_enforcement INTEGER NOT NULL DEFAULT 0,
                modules_json TEXT NOT NULL,
                auto_renew INTEGER NOT NULL DEFAULT 0,
                term_days INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                max_expires_at TEXT NOT NULL,
                renew_by TEXT NOT NULL,
                issued_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (licensee_id) REFERENCES licensees(id)
            );
            """
        )
        row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
        _sync_modules(conn)
        conn.commit()


def _sync_modules(conn: sqlite3.Connection) -> None:
    for item in catalog_rows():
        conn.execute(
            """
            INSERT INTO modules(id, label, requires_le, kind)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                label = excluded.label,
                requires_le = excluded.requires_le,
                kind = excluded.kind
            """,
            (item["id"], item["label"], 1 if item["requires_le"] else 0, item["kind"]),
        )


def list_modules() -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT id, label, requires_le, kind FROM modules ORDER BY id").fetchall()
    return [
        {
            "id": row["id"],
            "label": row["label"],
            "requires_le": bool(row["requires_le"]),
            "kind": row["kind"],
        }
        for row in rows
    ]


def upsert_licensee(*, name: str, email: str, address: str = "", licensee_id: str | None = None) -> dict[str, Any]:
    cleaned_name = (name or "").strip()
    cleaned_email = (email or "").strip()
    if not cleaned_name:
        raise AtoError("Licensee name is required")
    if not cleaned_email or "@" not in cleaned_email:
        raise AtoError("Licensee email is required")
    init_db()
    ident = (licensee_id or "").strip() or str(uuid.uuid4())
    now = _iso(_utcnow())
    with connect() as conn:
        existing = conn.execute("SELECT id FROM licensees WHERE id = ?", (ident,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE licensees SET name = ?, email = ?, address = ? WHERE id = ?",
                (cleaned_name, cleaned_email, (address or "").strip(), ident),
            )
        else:
            conn.execute(
                """
                INSERT INTO licensees(id, name, email, address, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ident, cleaned_name, cleaned_email, (address or "").strip(), now),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM licensees WHERE id = ?", (ident,)).fetchone()
    return dict(row)


def list_licensees() -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM licensees ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def list_licenses(licensee_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        if licensee_id:
            rows = conn.execute(
                "SELECT * FROM licenses WHERE licensee_id = ? ORDER BY created_at DESC",
                (licensee_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM licenses ORDER BY created_at DESC").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["modules"] = json.loads(item.get("modules_json") or "[]")
        except json.JSONDecodeError:
            item["modules"] = []
        result.append(item)
    return result


def _normalize_modules(modules: list[str], *, law_enforcement: bool) -> list[str]:
    cleaned: list[str] = []
    for raw in modules:
        key = normalize_module_id(str(raw))
        if not key or key in cleaned:
            continue
        if requires_law_enforcement(key) and not law_enforcement:
            raise AtoError("Red team ATO requires the law-enforcement flag")
        cleaned.append(key)
    if not cleaned:
        raise AtoError("Select at least one licensed module")
    return cleaned


def issue_customer_license(
    *,
    name: str,
    email: str,
    address: str = "",
    law_enforcement: bool = False,
    modules: list[str] | None = None,
    term_days: int = 90,
    max_days: int | None = None,
    auto_renew: bool = False,
    case_ref: str = "",
    output_dir: Path | None = None,
    licensee_id: str | None = None,
    max_expires_at: str | None = None,
) -> dict[str, Any]:
    """Mint a sealed, signed license and record it in the vendor SQLite DB."""
    licensee = upsert_licensee(name=name, email=email, address=address, licensee_id=licensee_id)
    selected = _normalize_modules(list(modules or []), law_enforcement=law_enforcement)
    if term_days < 1 or term_days > 3660:
        raise AtoError("term_days must be between 1 and 3660")
    cap_days = int(max_days) if max_days is not None else max(term_days, term_days * 4)
    if cap_days < term_days:
        raise AtoError("max_days must be at least term_days")

    private, _public = load_or_create_vendor_keys()
    document = issue_license(
        law_enforcement=law_enforcement,
        blue_team="blue-team" in selected,
        red_team="red-team" in selected,
        valid_days=term_days,
        renew_in_days=term_days,
        case_ref=case_ref,
        install=False,
        modules=selected,
        licensee_name=licensee["name"],
        licensee_email=licensee["email"],
        licensee_address=licensee["address"],
        jarvis_version=JARVIS_VERSION,
        auto_renew=auto_renew,
        term_days=term_days,
        max_days=cap_days,
        max_expires_at=max_expires_at,
        private_key=private,
    )
    payload = document["payload"]
    inner = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sealed = seal_bytes(inner)

    dest_dir = Path(output_dir) if output_dir is not None else issuer_data_dir() / "issued"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{payload['license_id']}.jarvis-license"
    dest.write_text(json.dumps(sealed, indent=2) + "\n", encoding="utf-8")
    pin_path = dest.with_suffix(".trusted.pub")
    pin_path.write_bytes(_public.public_bytes_raw())

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO licenses(
                license_id, licensee_id, jarvis_version, law_enforcement, modules_json,
                auto_renew, term_days, expires_at, max_expires_at, renew_by, issued_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["license_id"],
                licensee["id"],
                JARVIS_VERSION,
                1 if law_enforcement else 0,
                json.dumps(selected),
                1 if auto_renew else 0,
                term_days,
                payload["expires_at"],
                payload["max_expires_at"],
                payload["renew_by"],
                str(dest),
                payload["issued_at"],
            ),
        )
        conn.commit()

    return {
        "licensee": licensee,
        "license": document,
        "sealed_path": str(dest),
        "trusted_pub_path": str(pin_path),
        "vendor_public_key": vendor_public_hex(),
        "seal_public_key": product_seal_public_hex(),
    }


def renew_customer_license(license_id: str, *, output_dir: Path | None = None) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM licenses WHERE license_id = ?", (license_id,)).fetchone()
        if row is None:
            raise AtoError("No issuer record for that license_id")
        licensee = conn.execute("SELECT * FROM licensees WHERE id = ?", (row["licensee_id"],)).fetchone()
    if licensee is None:
        raise AtoError("Licensee record is missing")
    try:
        modules = json.loads(row["modules_json"] or "[]")
    except json.JSONDecodeError:
        modules = []
    max_expires = datetime.fromisoformat(str(row["max_expires_at"]).replace("Z", "+00:00"))
    now = _utcnow()
    remaining = int((max_expires - now).total_seconds() // 86400)
    if remaining < 1:
        raise AtoError("Cannot renew past signed max_expires_at")
    term_days = min(int(row["term_days"]), remaining)
    return issue_customer_license(
        name=licensee["name"],
        email=licensee["email"],
        address=licensee["address"],
        law_enforcement=bool(row["law_enforcement"]),
        modules=list(modules),
        term_days=term_days,
        auto_renew=bool(row["auto_renew"]),
        output_dir=output_dir,
        licensee_id=licensee["id"],
        max_expires_at=str(row["max_expires_at"]),
    )


# Re-export for the Tk app / CLI without importing cyber_ato directly everywhere.
__all__ = [
    "init_db",
    "issue_customer_license",
    "issuer_data_dir",
    "list_licensees",
    "list_licenses",
    "list_modules",
    "load_or_create_vendor_keys",
    "renew_customer_license",
    "upsert_licensee",
    "vendor_public_hex",
]
