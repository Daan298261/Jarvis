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

    java = Path(os.environ.get("JAVA_HOME", ""))
    sdk = Path(os.environ.get("ANDROID_HOME", os.environ.get("ANDROID_SDK_ROOT", "")))
    binary = ".exe" if os.name == "nt" else ""
    if not (java / "bin" / ("keytool" + binary)).is_file():
        raise RuntimeError("Set JAVA_HOME to JDK 17 before building")
    if not (sdk / "platforms" / "android-35" / "android.jar").is_file():
        raise RuntimeError("Set ANDROID_HOME and install SDK platform 35 (scripts/setup_android.ps1 on Windows)")

    folder = root() / "builds"
    folder.mkdir(exist_ok=True)
    keystore = folder / "jarvis-release.jks"
    password = secret_file(folder / "signing-password.sec")
    env = {**os.environ, "JARVIS_APK_KEYSTORE": str(keystore), "JARVIS_APK_PASSWORD": password}
    if not keystore.exists():
        progress("Creating the persistent release signing identity")
        subprocess.run(
            [
                str(java / "bin" / ("keytool" + binary)),
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
