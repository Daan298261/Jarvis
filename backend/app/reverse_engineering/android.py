"""Static DEX inspection and owner-approved Android emulator scenarios."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from . import provision, store

_INSTALL_LOCK = threading.Lock()
_EMULATOR_LOCK = asyncio.Lock()
PACKAGES = ["platform-tools", "emulator", "platforms;android-35", "build-tools;35.0.0",
            "system-images;android-35;google_apis;x86_64"]


def root() -> Path:
    p = provision.runtime_root() / "android"
    p.mkdir(exist_ok=True)
    return p


def readiness() -> dict:
    p = root() / "setup.json"
    return json.loads(p.read_text()) if p.exists() else {"status": "not_installed"}


def _state(**values):
    store.atomic_json(root() / "setup.json", values)
    return values


def _java() -> Path:
    candidates = list((root() / "jdk").glob("*/bin/java.exe"))
    if not candidates:
        raise RuntimeError("Android JDK has not been installed")
    return candidates[0]


def _env() -> dict:
    return {**os.environ, "JAVA_HOME": str(_java().parents[1]),
            "ANDROID_SDK_ROOT": str(root() / "sdk"), "ANDROID_HOME": str(root() / "sdk"),
            "ANDROID_AVD_HOME": str(root() / "avd")}


def _run(args: list[str], timeout=120, input=None, env=None) -> str:
    result = subprocess.run(args, capture_output=True, timeout=timeout, input=input, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).decode(errors="replace")[-3000:])
    return result.stdout.decode(errors="replace")


def _sdk_tool(name, args, timeout=120, input=None):
    classes = {"sdkmanager": "com.android.sdklib.tool.sdkmanager.SdkManagerCli",
               "avdmanager": "com.android.sdklib.tool.AvdManagerCli"}
    lib = root() / "sdk" / "cmdline-tools" / "19.0" / "lib"
    prop = "com.android.sdkmanager.toolsdir" if name == "avdmanager" else "com.android.sdklib.toolsdir"
    return _run([str(_java()), "-D" + prop + "=" + str(lib.parent),
                 "-cp", str(lib / "*"), classes[name], *args], timeout, input, _env())


def install() -> dict:
    if not _INSTALL_LOCK.acquire(False):
        return readiness()
    try:
        specs = json.loads(provision.LOCK_PATH.read_text())
        _state(status="installing", stage="Downloading verified JDK and Android tools")
        jdk = provision.download("jdk-windows.zip", specs["jdk_windows"])
        tools = provision.download("android-command-tools.zip", specs["android_tools"])
        for archive, dest in [(jdk, root() / "jdk"), (tools, root() / "sdk" / "cmdline-tools" / "19.0")]:
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    name = info.filename.removeprefix("cmdline-tools/") if archive == tools else info.filename
                    if not name or info.is_dir():
                        continue
                    target = (dest / name).resolve()
                    if not target.is_relative_to(dest.resolve()):
                        raise ValueError("SDK archive entry escapes destination")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        _state(status="installing", stage="Installing Android API 35 and emulator")
        _sdk_tool("sdkmanager", ["--sdk_root=" + str(root() / "sdk"), "--licenses"], input=b"y\n" * 100, timeout=300)
        _sdk_tool("sdkmanager", ["--sdk_root=" + str(root() / "sdk"), *PACKAGES], timeout=1800, input=b"y\n" * 100)
        (root() / "avd").mkdir(exist_ok=True)
        if not (root() / "avd" / "anzu_rea.ini").exists():
            _sdk_tool("avdmanager", ["create", "avd", "--name", "anzu_rea", "--package",
                                    PACKAGES[-1], "--device", "pixel_5", "--force"], input=b"no\n", timeout=300)
        versions = {p.parent.relative_to(root() / "sdk").as_posix(): p.read_text(errors="replace")
                    for p in (root() / "sdk").rglob("source.properties")}
        store.atomic_json(root() / "installed-packages.json", versions)
        return _state(status="ready", stage="Android emulator installed", packages=PACKAGES)
    except Exception as exc:
        _state(status="failed", stage="Android setup stopped; repair can retry", error=str(exc)[-4000:])
        raise
    finally:
        _INSTALL_LOCK.release()


def capture_schema() -> dict:
    return {"name": "android_capture", "description": "Approved APK install/launch and bounded UI steps on a disposable emulator.",
            "inputSchema": {"type": "object", "properties": {
                "package": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"},
                "activity": {"type": "string", "pattern": r"^\.?[A-Za-z][A-Za-z0-9_.$]*$"},
                "steps": {"type": "array", "maxItems": 30, "items": {"type": "object", "properties": {
                    "kind": {"enum": ["wait", "tap", "text", "key"]},
                    "milliseconds": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "x": {"type": "integer", "minimum": 0, "maximum": 4096},
                    "y": {"type": "integer", "minimum": 0, "maximum": 4096},
                    "text": {"type": "string", "maxLength": 200, "pattern": r"^[A-Za-z0-9 .,!?_@+-]*$"},
                    "keycode": {"enum": [4, 19, 20, 21, 22, 23, 61, 66]}}, "required": ["kind"],
                    "additionalProperties": False}}}, "required": ["package", "activity"], "additionalProperties": False}}


async def decompile(row: dict) -> dict:
    path = await asyncio.to_thread(provision.linux_path, row["snapshot"])
    out = store.directory(row["id"]) / "jadx"
    linux_out = await asyncio.to_thread(provision.linux_path, str(out))
    result = await asyncio.to_thread(provision.wsl, "env", "JAVA_HOME=/opt/anzu/jdk",
                                    "PATH=/opt/anzu/jdk/bin:/usr/bin:/bin", "/opt/anzu/jadx/bin/jadx",
                                    "--no-res", "-d", linux_out, path, timeout=600)
    return {"provider": "JADX 1.5.6", "output_root": str(out),
            "java_files": [p.relative_to(out).as_posix() for p in out.rglob("*.java")],
            "diagnostics": result[-4000:], "limitations": ["Recovered Java is decompiler output.", "No execution was observed."]}


async def capture(row: dict, args: dict) -> dict:
    from jsonschema import validate
    validate(args, capture_schema()["inputSchema"])
    for step in args.get("steps", []):
        required = {"tap": {"x", "y"}, "text": {"text"}, "key": {"keycode"}, "wait": {"milliseconds"}}[step["kind"]]
        if not required.issubset(step):
            raise ValueError("Scenario step is missing required fields")
    if Path(row["target"]).suffix.lower() != ".apk":
        raise ValueError("Android execution requires a prepared APK")
    if readiness().get("status") != "ready":
        raise RuntimeError("Android emulator setup is not ready")
    async with _EMULATOR_LOCK:
        return await _capture(row, args)


async def _capture(row: dict, args: dict) -> dict:
    sdk = root() / "sdk"
    adb = str(sdk / "platform-tools" / "adb.exe")
    port = None
    for candidate in range(5580, 5680, 2):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise RuntimeError("No free dedicated emulator port")
    serial = f"emulator-{port}"
    out = store.directory(row["id"]) / "android-capture"
    out.mkdir(exist_ok=True)
    log = (out / "emulator.log").open("wb")
    proc = subprocess.Popen([str(sdk / "emulator" / "emulator.exe"), "-avd", "anzu_rea",
                             "-port", str(port), "-read-only", "-no-snapshot", "-wipe-data",
                             "-no-window", "-no-audio", "-no-boot-anim", "-gpu", "swiftshader_indirect"],
                            env=_env(), stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    async def command(*argv, timeout=60):
        return await asyncio.to_thread(_run, [adb, "-s", serial, *argv], timeout)
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("Emulator exited before boot; inspect saved emulator.log")
            try:
                if (await command("shell", "getprop", "sys.boot_completed", timeout=10)).strip() == "1":
                    break
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            await asyncio.sleep(2)
        else:
            raise TimeoutError("Emulator did not boot within 180 seconds")
        await command("install", "--no-streaming", "-r", row["snapshot"], timeout=120)
        launched = await command("shell", "am", "start", "-W", "-n", args["package"] + "/" + args["activity"])
        if "Error:" in launched:
            raise RuntimeError(launched)
        observations = []
        for i, step in enumerate([{"kind": "wait", "milliseconds": 500}, *args.get("steps", [])]):
            kind = step["kind"]
            if kind == "wait":
                await asyncio.sleep(step["milliseconds"] / 1000)
            elif kind == "tap":
                await command("shell", "input", "tap", str(step["x"]), str(step["y"]))
            elif kind == "key":
                await command("shell", "input", "keyevent", str(step["keycode"]))
            else:
                await command("shell", "input", "text", step["text"].replace(" ", "%s"))
            await command("shell", "uiautomator", "dump", "/sdcard/anzu-rea.xml")
            xml = await command("shell", "cat", "/sdcard/anzu-rea.xml")
            if len(xml.encode("utf-8")) > 4 * 1024**2:
                raise ValueError("UI dump exceeds 4 MiB limit")
            import xml.etree.ElementTree as ET
            tree = ET.fromstring(xml)
            for node in tree.iter():
                if node.attrib.get("password") == "true":
                    node.set("text", "[redacted]")
                    node.set("content-desc", "[redacted]")
            xml = ET.tostring(tree, encoding="unicode")
            (out / f"step-{i}.xml").write_text(xml, encoding="utf-8")
            observations.append({"step": i, "action": step, "ui": xml})
        return {"provider": "Android API 35 emulator / ADB", "serial": serial, "package": args["package"],
                "target_sha256": row["sha256"], "observations": observations,
                "limitations": ["Only the declared UI scenario was observed.", "No network or native-call tracing is claimed."]}
    finally:
        try:
            await command("emu", "kill", timeout=10)
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, 15)
        except subprocess.TimeoutExpired:
            proc.kill()
            await asyncio.to_thread(proc.wait, 10)
        log.close()
