"""Build a signed Android companion APK locally; never upload signing keys.

Personalized (default):
  python scripts/build_android.py --endpoint https://192.168.1.10:4781

Generic (pair-in-app; full feature set for releases):
  python scripts/build_android.py --generic

Requires JDK17, ANDROID_HOME, Node, and this repository's backend dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

REQUIRED_COMPANION_FEATURES = (
    "chat",
    "tasks",
    "attachments",
    "realtime_voice",
    "calls",
    "schedules",
    "whatsapp_contact",
    "apex_orb",
)

_JAVA_MISSING = (
    "JDK 17 was not found. Install Eclipse Temurin 17 "
    "(winget install EclipseAdoptium.Temurin.17.JDK) or set JAVA_HOME to that JDK."
)
_ANDROID_MISSING = (
    "Android SDK platform 35 was not found. Run scripts/setup_android.ps1 "
    "or set ANDROID_HOME to an SDK that includes platforms/android-35."
)


def _exe(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def _is_jdk_home(path: Path) -> bool:
    return (path / "bin" / _exe("java")).is_file() and (path / "bin" / _exe("keytool")).is_file()


def _java_major(java_home: Path) -> int | None:
    java = java_home / "bin" / _exe("java")
    try:
        proc = subprocess.run(
            [str(java), "-version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    blob = f"{proc.stderr or ''}\n{proc.stdout or ''}"
    match = re.search(r'version "(?:1\.)?(\d+)', blob)
    if match:
        return int(match.group(1))
    return None


def _windows_jdk_candidates() -> list[Path]:
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    local_app = Path(os.environ.get("LOCALAPPDATA") or "")
    roots = [
        program_files / "Eclipse Adoptium",
        program_files / "Microsoft",
        program_files / "Java",
        program_files / "AdoptOpenJDK",
        program_files / "Amazon Corretto",
        program_files / "Zulu",
        local_app / "Programs" / "Eclipse Adoptium",
        Path.home() / ".jdks",
    ]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name, reverse=True)
        except OSError:
            continue
        for child in children:
            if child.is_dir() and _is_jdk_home(child):
                found.append(child)
    studio_jbr = program_files / "Android" / "Android Studio" / "jbr"
    if _is_jdk_home(studio_jbr):
        found.append(studio_jbr)
    return found


def _jdk_candidates() -> list[Path]:
    if os.name == "nt":
        return _windows_jdk_candidates()
    return []


def resolve_java_home() -> Path:
    """Prefer JAVA_HOME, then a locally installed JDK 17 (common Windows paths)."""
    explicit = Path(os.environ.get("JAVA_HOME") or "")
    if str(explicit) and _is_jdk_home(explicit):
        return explicit
    named_17: list[Path] = []
    others: list[Path] = []
    for candidate in _jdk_candidates():
        name = candidate.name.lower()
        if "jdk-17" in name or "jdk17" in name or "-17." in name:
            named_17.append(candidate)
        else:
            others.append(candidate)
    for candidate in named_17 + others:
        major = _java_major(candidate)
        if major == 17:
            return candidate
        if "jdk-17" in candidate.name.lower() or "jdk17" in candidate.name.lower():
            return candidate
    raise RuntimeError(_JAVA_MISSING)


def resolve_android_sdk() -> Path:
    """Prefer ANDROID_HOME, then the Jarvis/Android Studio SDK folders on this PC."""
    local_app = Path(os.environ.get("LOCALAPPDATA") or "")
    candidates = [
        os.environ.get("ANDROID_HOME") or "",
        os.environ.get("ANDROID_SDK_ROOT") or "",
        str(local_app / "Jarvis" / "android-sdk") if local_app else "",
        str(local_app / "Android" / "Sdk") if local_app else "",
        str(Path.home() / "Android" / "Sdk"),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if (path / "platforms" / "android-35" / "android.jar").is_file():
            return path
    raise RuntimeError(_ANDROID_MISSING)


def secret_file(path: Path) -> str:
    """Persist the signing password with DPAPI on Windows or owner-only Unix mode."""
    if os.name == "nt":
        import win32crypt

        if path.exists():
            return win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1].decode()
        value = secrets.token_urlsafe(36)
        path.write_bytes(win32crypt.CryptProtectData(value.encode(), "Jarvis APK signing", None, None, None, 0))
        return value
    if path.exists():
        return path.read_text(encoding="utf-8")
    value = secrets.token_urlsafe(36)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(value)
    return value


def ensure_feature_sources() -> None:
    """Fail closed if the companion tree is missing a required feature surface."""
    base = REPO / "android" / "app" / "src" / "main"
    kotlin = base / "java" / "com" / "jarvis" / "companion"
    manifest = (base / "AndroidManifest.xml").read_text(encoding="utf-8")
    model = (kotlin / "CompanionModel.kt").read_text(encoding="utf-8")
    checks = {
        "chat": (kotlin / "MainActivity.kt").is_file(),
        "tasks": "fun approve" in model or "/tasks" in model,
        "attachments": (
            ("action.SEND" in manifest or "SEND_MULTIPLE" in manifest) and "fun upload" in model
        ),
        "realtime_voice": (kotlin / "RealtimeVoiceSession.kt").is_file(),
        "calls": (kotlin / "Calls.kt").is_file() and ".CallService" in manifest,
        "schedules": "/schedules" in model,
        "whatsapp_contact": "WRITE_CONTACTS" in manifest and "addJarvisWhatsAppContact" in model,
        "apex_orb": True,  # verified after the vite bundle step
    }
    missing = [name for name in REQUIRED_COMPANION_FEATURES if name != "apex_orb" and not checks.get(name)]
    if missing:
        raise RuntimeError(
            "Companion sources are missing required features for a release APK: " + ", ".join(missing)
        )


def bundle_orb(env: dict[str, str], progress) -> None:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("Node.js/npm are required to bundle the shared Apex renderer")
    progress("Bundling the shared Apex orb")
    subprocess.run(
        [npm, "ci", "--no-audit", "--no-fund"],
        cwd=REPO / "frontend",
        env=env,
        check=True,
        capture_output=True,
    )
    orb_config = "vite.orb.config.ts"
    if not (REPO / "frontend" / orb_config).is_file():
        raise RuntimeError(f"Missing frontend/{orb_config}")
    subprocess.run(
        [npm, "exec", "--", "vite", "build", "--config", orb_config],
        cwd=REPO / "frontend",
        env=env,
        check=True,
        capture_output=True,
    )
    orb_index = REPO / "android" / "app" / "src" / "main" / "assets" / "orb" / "index.html"
    if not orb_index.is_file():
        raise RuntimeError("Apex orb assets were not produced; companion APK would lack presence UI")


def build(
    endpoint: str | None = None,
    progress=lambda message: print(message, flush=True),
    firebase: dict | None = None,
    endpoints: list[str] | None = None,
    *,
    generic: bool = False,
) -> dict:
    from app.mobile.connectivity import origin
    from app.mobile.gateway import server_identity
    from app.mobile.store import root

    ensure_feature_sources()

    java = resolve_java_home()
    sdk = resolve_android_sdk()
    progress(f"Using JDK at {java}")
    progress(f"Using Android SDK at {sdk}")

    folder = root() / "builds"
    folder.mkdir(exist_ok=True)
    keystore = folder / "jarvis-release.jks"
    password = secret_file(folder / "signing-password.sec")
    env = {
        **os.environ,
        "JAVA_HOME": str(java),
        "ANDROID_HOME": str(sdk),
        "ANDROID_SDK_ROOT": str(sdk),
        "JARVIS_APK_KEYSTORE": str(keystore),
        "JARVIS_APK_PASSWORD": password,
    }
    if not keystore.exists():
        progress("Creating the persistent release signing identity")
        subprocess.run(
            [
                str(java / "bin" / _exe("keytool")),
                "-genkeypair",
                "-keystore",
                str(keystore),
                "-alias",
                "jarvis",
                "-storepass:env",
                "JARVIS_APK_PASSWORD",
                "-keypass:env",
                "JARVIS_APK_PASSWORD",
                "-keyalg",
                "RSA",
                "-keysize",
                "3072",
                "-validity",
                "10000",
                "-dname",
                "CN=Jarvis Companion",
            ],
            env=env,
            check=True,
            capture_output=True,
        )

    if firebase is None and os.environ.get("JARVIS_FIREBASE_CLIENT_CONFIG"):
        firebase = json.loads(Path(os.environ["JARVIS_FIREBASE_CLIENT_CONFIG"]).read_text(encoding="utf-8"))

    if generic:
        progress("Preparing generic companion bootstrap (pair after install)")
        settings: dict = {"mode": "generic", "features": list(REQUIRED_COMPANION_FEATURES)}
        if firebase:
            settings["firebase"] = firebase
        label = "generic"
    else:
        if not endpoint:
            raise ValueError("Personalized builds require an HTTPS gateway endpoint")
        endpoint = origin(endpoint)
        endpoints = list(dict.fromkeys([endpoint] + [origin(value) for value in endpoints or []]))[:8]
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.query
            or parsed.fragment
            or parsed.path.strip("/")
        ):
            raise ValueError("Endpoint must be an HTTPS origin without credentials, query or path")
        identity = server_identity([urlsplit(value).hostname for value in endpoints])
        settings = {
            "mode": "personalized",
            "endpoint": endpoint.rstrip("/"),
            "endpoints": endpoints,
            "server_pin": identity["server_pin"],
            "features": list(REQUIRED_COMPANION_FEATURES),
        }
        if firebase:
            settings["firebase"] = firebase
        label = "personalized"

    bootstrap = folder / f"bootstrap-{label}.json"
    bootstrap.write_text(json.dumps(settings), encoding="utf-8")
    bundle_orb(env, progress)
    progress(f"Compiling and signing the {label} companion APK")
    release_code = int(time.time() // 60)
    subprocess.run(
        [
            str(REPO / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")),
            ":app:assembleRelease",
            f"-PbootstrapFile={bootstrap}",
            f"-PreleaseCode={release_code}",
            "--console=plain",
        ],
        cwd=REPO / "android",
        env=env,
        check=True,
        capture_output=True,
    )
    source = REPO / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
    verifier = sdk / "build-tools" / "35.0.0" / ("apksigner.bat" if os.name == "nt" else "apksigner")
    subprocess.run([str(verifier), "verify", str(source)], env=env, check=True, capture_output=True)
    target = folder / (f"JarvisCompanion-generic-{release_code}.apk" if generic else f"jarvis-{release_code}.apk")
    shutil.copyfile(source, target)
    result = {
        "filename": target.name,
        "path": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "mode": "generic" if generic else "personalized",
        "features": list(REQUIRED_COMPANION_FEATURES),
    }
    if not generic:
        result["endpoint"] = settings["endpoint"]
        result["server_pin"] = settings["server_pin"]
    progress("APK signature verified; ready to install")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="", help="HTTPS gateway origin for a personalized APK")
    parser.add_argument(
        "--generic",
        action="store_true",
        help="Build a full-featured generic companion APK (pair in the app after install)",
    )
    args = parser.parse_args()
    if args.generic:
        print(json.dumps(build(generic=True), indent=2))
    else:
        if not args.endpoint:
            parser.error("--endpoint is required unless --generic is set")
        print(json.dumps(build(args.endpoint), indent=2))


if __name__ == "__main__":
    main()
