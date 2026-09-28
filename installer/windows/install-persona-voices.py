"""Prepare selected neural voices shared by the 13 named personas during setup."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.persona.named_persona import ROSTER  # noqa: E402
from app.tts.pack_install import install_voice_pack  # noqa: E402
from app.voice_profiles.catalog import get_catalog  # noqa: E402

ROSTER_VOICE_IDS = tuple(dict.fromkeys(row.voice_profile_id for row in ROSTER))


def selected_profile_ids(argv: list[str] | None = None) -> list[str]:
    if argv is None:
        return list(ROSTER_VOICE_IDS)
    args = [item.strip() for item in argv if item.strip()]
    if args == ["none"]:
        return []
    if args:
        unknown = [item for item in args if item not in ROSTER_VOICE_IDS]
        if unknown:
            raise SystemExit(f"Unknown voice profile id(s): {', '.join(unknown)}")
        return list(dict.fromkeys(args))
    return list(ROSTER_VOICE_IDS)


def main(argv: list[str] | None = None) -> int:
    profile_ids = selected_profile_ids(argv)
    if not profile_ids:
        print("No extra persona voices selected.", flush=True)
        return 0
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
        print(
            f"Persona voices pending: {', '.join(failed)}. Download them in the Persona or Voice menu.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(f"Persona voices ready ({len(profile_ids)} selected packs).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
