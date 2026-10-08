#!/usr/bin/env python3
"""Score the fixed front-lane prompts and, when weights exist, time one token.

Does not change the 1500 ms front timeout. Missing GGUF or llama-server is
reported as not measured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.front_benchmark import (  # noqa: E402
    measure_live_first_token,
    measure_runtime,
    run_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Front-lane benchmark")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Start the local front server and time one token when the GGUF exists",
    )
    parser.add_argument("--profile", default="front_2b")
    args = parser.parse_args()
    report = run_benchmark(allow_live=args.live)
    if args.live:
        available, _detail = True, ""
        runtime = measure_runtime(args.profile)
        if not runtime.get("measured") and runtime.get("reason") and "missing" in str(runtime.get("reason")).lower():
            available = False
        if "missing" in str(runtime.get("reason") or "").lower() or "llama-server" in str(runtime.get("reason") or ""):
            available = False
        if available:
            live = asyncio.run(measure_live_first_token(args.profile))
            report["live"] = live
            path = Path(report["path"])
            path.write_text(json.dumps({k: v for k, v in report.items() if k != "path"}, indent=2), encoding="utf-8")
        else:
            report["live"] = {"measured": False, "reason": runtime.get("reason")}
    print(json.dumps({k: v for k, v in report.items() if k != "quality" or True}, indent=2)[:8000])
    quality = report.get("quality") or {}
    print(
        f"quality_accuracy={quality.get('accuracy')} spoken_usable={quality.get('spoken_usable')} "
        f"timeout_ms={report.get('timeout_ms')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
