"""Build a signed, personalized Android APK locally; never upload signing keys.

python scripts/build_android.py --endpoint https://192.168.1.10:4781
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
        return path.read_text()
    value = secrets.token_urlsafe(36)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(value)
    return value


def build(endpoint: str, progress=lambda message: print(message, flush=True), firebase: dict | None = None, endpoints: list[str] | None = None) -> dict:
    from app.mobile.gateway import server_identity
    from app.mobile.identity import invite
    from app.mobile.store import root
    from app.mobile.connectivity import origin
    endpoint = origin(endpoint)
    endpoints = list(dict.fromkeys([endpoint] + [origin(value) for value in endpoints or []]))[:8]
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path.strip("/"):
        raise ValueError("Endpoint must be an HTTPS origin without credentials, query or path")
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
        subprocess.run([str(java / "bin" / ("keytool" + binary)), "-genkeypair", "-keystore", str(keystore), "-alias", "jarvis",
                        "-storepass:env", "JARVIS_APK_PASSWORD", "-keypass:env", "JARVIS_APK_PASSWORD",
                        "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000", "-dname", "CN=Jarvis Companion"], env=env, check=True, capture_output=True)
    identity = server_identity([urlsplit(value).hostname for value in endpoints])
    invitation = invite(3600)
    settings = {"endpoint": endpoint.rstrip("/"), "endpoints": endpoints, "server_pin": identity["server_pin"], "invitation": invitation["invitation"]}
    if firebase is None and os.environ.get("JARVIS_FIREBASE_CLIENT_CONFIG"):
        firebase = json.loads(Path(os.environ["JARVIS_FIREBASE_CLIENT_CONFIG"]).read_text())
    if firebase:
        settings["firebase"] = firebase
    bootstrap = folder / "bootstrap.json"
    bootstrap.write_text(json.dumps(settings), encoding="utf-8")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("Node.js/npm are required to bundle the shared Apex renderer")
    progress("Bundling the shared Apex orb")
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=REPO / "frontend", env=env, check=True, capture_output=True)
    subprocess.run([npm, "exec", "--", "vite", "build", "--config", "vite.orb.config.ts"], cwd=REPO / "frontend", env=env, check=True, capture_output=True)
    progress("Compiling and signing the personalized APK")
    # Monotonic minute-based version code keeps updates compatible, including retries.
    release_code = int(time.time() // 60)
    subprocess.run([str(REPO / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")), ":app:assembleRelease",
                    f"-PbootstrapFile={bootstrap}", f"-PreleaseCode={release_code}", "--console=plain"], cwd=REPO / "android", env=env, check=True, capture_output=True)
    source = REPO / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
    verifier = sdk / "build-tools" / "35.0.0" / ("apksigner.bat" if os.name == "nt" else "apksigner")
    subprocess.run([str(verifier), "verify", str(source)], env=env, check=True, capture_output=True)
    target = folder / f"jarvis-{release_code}.apk"
    shutil.copyfile(source, target)
    result = {"filename": target.name, "path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "endpoint": settings["endpoint"], "server_pin": settings["server_pin"], "invitation_expires_at": invitation["expires_at"]}
    progress("APK signature verified; ready to install")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.endpoint), indent=2))


if __name__ == "__main__":
    main()
