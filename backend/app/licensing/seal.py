"""Optional X25519 + ChaCha20-Poly1305 seal for .jarvis-license files (RFC-0087).

Authenticity is Ed25519 (vendor signing key). This box only hides licensee PII
at rest. The product unseal private key is extractable from Jarvis; that is
accepted. Forgery still requires the issuer signing key.
"""
from __future__ import annotations

import os
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

SEAL_FORMAT = "jarvis-license-v1"
_SEAL_INFO = b"jarvis-license-v1"

# Product identity for sealing. Public half is used by the vendor issuer.
DEFAULT_SEAL_PRIVATE_KEY_HEX = "281f9966bed09f81178dc185be664c34286b1ec1f0de785f1e89c063f16edb68"
DEFAULT_SEAL_PUBLIC_KEY_HEX = "eb47d31e1147b8500266ae70b3632b9376c1627b351ca8900d276564b86c6b78"


class SealError(ValueError):
    pass


def _load_private(hex_key: str | None = None) -> X25519PrivateKey:
    override = (os.environ.get("JARVIS_LICENSE_SEAL_PRIVATE_KEY") or "").strip()
    raw_hex = override or hex_key or DEFAULT_SEAL_PRIVATE_KEY_HEX
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise SealError("Seal private key is not valid hex") from exc
    if len(data) != 32:
        raise SealError("Seal private key must be 32 bytes")
    return X25519PrivateKey.from_private_bytes(data)


def _load_public(hex_key: str | None = None) -> X25519PublicKey:
    override = (os.environ.get("JARVIS_LICENSE_SEAL_PUBLIC_KEY") or "").strip()
    raw_hex = override or hex_key or DEFAULT_SEAL_PUBLIC_KEY_HEX
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise SealError("Seal public key is not valid hex") from exc
    if len(data) != 32:
        raise SealError("Seal public key must be 32 bytes")
    return X25519PublicKey.from_public_bytes(data)


def product_seal_public_hex() -> str:
    return (os.environ.get("JARVIS_LICENSE_SEAL_PUBLIC_KEY") or "").strip() or DEFAULT_SEAL_PUBLIC_KEY_HEX


def _derive_aead_key(shared: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_SEAL_INFO,
    ).derive(shared)


def is_sealed_document(document: Any) -> bool:
    return isinstance(document, dict) and document.get("format") == SEAL_FORMAT


def seal_bytes(plaintext: bytes, *, recipient_public: X25519PublicKey | None = None) -> dict[str, str]:
    public = recipient_public or _load_public()
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(public)
    key = _derive_aead_key(shared)
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, plaintext, None)
    return {
        "format": SEAL_FORMAT,
        "ephemeral_pub": ephemeral.public_key().public_bytes_raw().hex(),
        "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex(),
    }


def unseal_bytes(document: dict[str, Any], *, recipient_private: X25519PrivateKey | None = None) -> bytes:
    if not is_sealed_document(document):
        raise SealError("Not a sealed Jarvis license")
    try:
        ephemeral_pub = X25519PublicKey.from_public_bytes(bytes.fromhex(str(document.get("ephemeral_pub") or "")))
        nonce = bytes.fromhex(str(document.get("nonce") or ""))
        ciphertext = bytes.fromhex(str(document.get("ciphertext") or ""))
    except ValueError as exc:
        raise SealError("Sealed license fields are not valid hex") from exc
    private = recipient_private or _load_private()
    shared = private.exchange(ephemeral_pub)
    key = _derive_aead_key(shared)
    try:
        return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise SealError("Sealed license could not be decrypted") from exc
