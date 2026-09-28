"""Prepare every neural voice shared by the 13 named personas during setup."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.persona.named_persona import ROSTER  # noqa: E402
from app.tts.pack_install import install_voice_pack  # noqa: E402
from app.voice_profiles.catalog import get_catalog  # noqa: E402


def main() -> int:
    profile_ids = dict.fromkeys(row.voice_profile_id for row in ROSTER)
    catalog = get_catalog()
    failed: list[str] = []
    for profile_id in profile_ids:
        profile = catalog.get(profile_id)
        if profile is None:
            print(f"Missing persona voice profile: {profile_id}", file=sys.stderr, flush=True)
            failed.append(profile_id)
            continue
        print(f"Preparing persona voice {profile_id}...", flush=True)
        try:
            result = install_voice_pack(profile)
            if not result.ok:
                raise RuntimeError(result.detail)
        except Exception as exc:
            print(f"{profile_id}: {exc}", file=sys.stderr, flush=True)
            failed.append(profile_id)
    if failed:
        print(f"Persona voices pending: {', '.join(failed)}. Download them in the Persona or Voice menu.", file=sys.stderr, flush=True)
        return 1
    print(f"Persona voices ready ({len(profile_ids)} shared packs for {len(ROSTER)} personas).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
