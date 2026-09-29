#!/usr/bin/env python3
"""CLI for installer/bootstrap: scan and register local GGUF files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.inference.model_discovery import register_all_from_scan, scan_local_ggufs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover local GGUF weights for Jarvis")
    parser.add_argument("--deep", action="store_true", help="Scan bounded drive locations (Windows)")
    parser.add_argument("--import", dest="do_import", action="store_true", help="Register newly found models")
    args = parser.parse_args()
    if args.do_import:
        payload = register_all_from_scan(deep=args.deep)
    else:
        payload = scan_local_ggufs(deep=args.deep)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
