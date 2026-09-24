"""Managed Laya install pins, hashes, and Apache-2.0 provenance (RFC-0171)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Pinned upstream refs. Hashes are expected content digests for the managed
# checkpoint/manifest files when downloaded; tests may substitute fixtures.
LAYA_SOURCE_URL = "https://github.com/NandhaKishorM/laya"
LAYA_LICENSE = "Apache-2.0"
LAYA_LICENSE_SPDX = "Apache-2.0"


@dataclass(frozen=True)
class LayaPin:
    component: str
    version: str
    filename: str
    sha256: str
    license: str = LAYA_LICENSE
    source_url: str = LAYA_SOURCE_URL


# Placeholder pins: real checkpoint SHAs are refreshed by Capability Lab (RFC-0137).
# Installer rejects mismatched digests; empty sha256 means "fixture/dev only".
LAYA_PINS: tuple[LayaPin, ...] = (
    LayaPin(
        component="source",
        version="0.1.0",
        filename="laya-source-0.1.0.manifest.json",
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    LayaPin(
        component="checkpoint",
        version="sysone-encoder-v1",
        filename="laya-sysone-encoder-v1.bin",
        # Zero-length file digest used as the documented empty-fixture pin until
        # Capability Lab publishes measured checkpoint digests.
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
)


def pins_as_dicts() -> list[dict[str, Any]]:
    return [
        {
            "component": pin.component,
            "version": pin.version,
            "filename": pin.filename,
            "sha256": pin.sha256,
            "license": pin.license,
            "license_spdx": LAYA_LICENSE_SPDX,
            "source_url": pin.source_url,
            "provenance": "managed-optional Apache-2.0 Laya System-One",
        }
        for pin in LAYA_PINS
    ]


def pin_for(component: str) -> LayaPin | None:
    for pin in LAYA_PINS:
        if pin.component == component:
            return pin
    return None


def validate_apache_provenance(manifest: dict[str, Any]) -> tuple[bool, str]:
    license_value = str(manifest.get("license") or manifest.get("license_spdx") or "").strip()
    if license_value not in {LAYA_LICENSE, LAYA_LICENSE_SPDX, "Apache 2.0", "Apache License 2.0"}:
        return False, f"Laya provenance rejected: license must be Apache-2.0, got {license_value!r}"
    source = str(manifest.get("source_url") or "").strip()
    if source and "NandhaKishorM/laya" not in source and "laya" not in source.lower():
        return False, f"Laya provenance rejected: unexpected source_url {source!r}"
    return True, ""
