"""RFC-0198 LTA protected-folder error taxonomy (honest failures only)."""

from __future__ import annotations

from typing import Any


class LtaError(Exception):
    """Base error with a stable machine code for API / job status."""

    code: str = "lta_error"

    def __init__(self, message: str = "", *, detail: str = "") -> None:
        text = (message or self.code).strip()
        super().__init__(text)
        self.detail = (detail or "").strip()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": str(self)}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class ManifestNotFound(LtaError):
    code = "manifest_not_found"


class XmlInvalid(LtaError):
    code = "xml_invalid"


class CertNotFound(LtaError):
    code = "cert_not_found"


class NoPrivateKey(LtaError):
    code = "no_private_key"


class DecryptFailed(LtaError):
    code = "decrypt_failed"


class ArchiveFailed(LtaError):
    code = "archive_failed"


class PathDenied(LtaError):
    code = "path_denied"


class PlatformUnsupported(LtaError):
    code = "platform_unsupported"


# Stable codes for API docs / tests.
LTA_ERROR_CODES: frozenset[str] = frozenset(
    {
        ManifestNotFound.code,
        XmlInvalid.code,
        CertNotFound.code,
        NoPrivateKey.code,
        DecryptFailed.code,
        ArchiveFailed.code,
        PathDenied.code,
        PlatformUnsupported.code,
    }
)
