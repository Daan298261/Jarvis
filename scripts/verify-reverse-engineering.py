"""Real-provider acceptance on source-owned fixtures; results are never mocked."""
from __future__ import annotations

import argparse
import asyncio
import json
import plistlib
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.reverse_engineering import android, provision, store
from app.reverse_engineering.runtime import Investigations


def build_fixtures(p: Path, mobile: bool):
    p.mkdir(parents=True, exist_ok=True)
    native = p / "native.c"
    native.write_text('__declspec(dllexport) const char *storage_key(void){return "ANZU_STORE_V1";}\n'
                      '__declspec(dllexport) int compute(int x){return x*7+3;}\n'
                      'void entry(void){volatile int result=compute(storage_key()[0]);}\n')
    linux = provision.linux_path(str(p))
    provision.wsl("clang", "--target=x86_64-pc-windows-msvc", "-O0", "-c", linux + "/native.c",
                  "-o", linux + "/native.obj", timeout=60)
    provision.wsl("lld-link", "/entry:entry", "/subsystem:console", "/nodefaultlib",
                  "/out:" + linux + "/fixture.exe", linux + "/native.obj", timeout=60)
    managed = p / "Storage.cs"
    managed.write_text('public class Storage { public static string Key() { return "ANZU_STORE_V1"; } '
                       'public static int Compute(int x) { return x * 7 + 3; } }')
    subprocess.run([r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe", "/nologo", "/target:library",
                    "/out:" + str(p / "Managed.dll"), str(managed)], check=True, capture_output=True)
    js = p / "electron"
    js.mkdir(exist_ok=True)
    (js / "package.json").write_text('{"name":"anzu-fixture","version":"1.0.0","main":"main.js"}')
    (js / "main.js").write_text('const {ipcMain}=require("electron");\n'
                               'ipcMain.handle("storage:key",()=> "ANZU_STORE_V1");\n')
    subprocess.run([provision.host_node(), str(provision.runtime_root() / "host/node_modules/@electron/asar/bin/asar.mjs"),
                    "pack", str(js), str(p / "fixture.asar")], check=True, capture_output=True)
    with zipfile.ZipFile(p / "fixture.ipa", "w") as z:
        z.writestr("Payload/Fixture.app/Info.plist", plistlib.dumps({"CFBundleIdentifier": "org.anzu.fixture", "CFBundleName": "ANZU_STORE_V1"}))
        z.writestr("Payload/Fixture.app/settings.json", '{"storageKey":"ANZU_STORE_V1"}')
    if mobile:
        build_apk(p)


def build_apk(p: Path):
    sdk = android.root() / "sdk"
    java = android._java()
    classes, dex = p / "classes", p / "dex"
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    source = p / "MainActivity.java"
    source.write_text('package org.anzu.fixture; public class MainActivity extends android.app.Activity {'
                      'public void onCreate(android.os.Bundle b){super.onCreate(b);android.widget.TextView t=new android.widget.TextView(this);'
                      't.setText("ANZU_STORE_V1");setContentView(t);}}')
    manifest = p / "AndroidManifest.xml"
    manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.anzu.fixture">'
                        '<uses-sdk android:minSdkVersion="23" android:targetSdkVersion="35"/>'
                        '<application android:label="ANZU fixture"><activity android:name=".MainActivity" android:exported="true">'
                        '<intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/>'
                        '</intent-filter></activity></application></manifest>')
    androidjar = str(sdk / "platforms/android-35/android.jar")
    cmds = [
        [str(java.with_name("javac.exe")), "-source", "8", "-target", "8", "-cp", androidjar, "-d", str(classes), str(source)],
        [str(java), "-cp", str(sdk / "build-tools/35.0.0/lib/d8.jar"), "com.android.tools.r8.D8",
         "--lib", androidjar, "--output", str(dex), *[str(c) for c in classes.rglob("*.class")]],
        [str(sdk / "build-tools/35.0.0/aapt.exe"), "package", "-f", "-M", str(manifest), "-I", androidjar, "-F", str(p / "fixture.apk")],
    ]
    for cmd in cmds:
        subprocess.run(cmd, check=True, capture_output=True)
    with zipfile.ZipFile(p / "fixture.apk", "a") as z:
        z.write(dex / "classes.dex", "classes.dex")
    key = p / "fixture-debug.jks"
    if not key.exists():
        subprocess.run([str(java.with_name("keytool.exe")), "-genkeypair", "-keystore", str(key), "-storepass", "android",
                        "-keypass", "android", "-alias", "fixture", "-dname", "CN=ANZU source-owned test", "-keyalg", "RSA",
                        "-validity", "365"], check=True, capture_output=True)
    subprocess.run([str(java), "-jar", str(sdk / "build-tools/35.0.0/lib/apksigner.jar"), "sign",
                    "--ks", str(key), "--ks-pass", "pass:android", str(p / "fixture.apk")], check=True, capture_output=True)


async def verify(p: Path, mobile: bool):
    service = Investigations()
    results = []
    cases = [
        ("native PE", p / "fixture.exe", [("open_binary", {}), ("search_strings", {"pattern": "ANZU_STORE_V1"}),
                                          ("procedure_pseudo_code", {"procedure": "compute"})]),
        (".NET", p / "Managed.dll", [("inspect_managed_artifact", {}), ("inspect_managed_members", {})]),
        ("Electron ASAR", p / "fixture.asar", [("analyze_javascript_application", {}),
                                               ("materialize_artifact", {}), ("read_artifact_source", {"path": "derived/main.js"})]),
        ("IPA static package", p / "fixture.ipa", [("open_binary", {}), ("inspect_artifact", {}),
                                                  ("materialize_artifact", {}),
                                                  ("read_artifact_source", {"path": "derived/Payload/Fixture.app/settings.json"})]),
    ]
    if mobile:
        cases.append(("APK static", p / "fixture.apk", [("open_binary", {}), ("inspect_artifact", {}),
                                                        ("android_decompile", {}),
                                                        ("read_artifact_source", {"path": "jadx/sources/org/anzu/fixture/MainActivity.java"})]))
    try:
        for name, target, operations in cases:
            try:
                row = await service.prepare(str(target), "Find ANZU_STORE_V1 and explain available code evidence.", [str(p)], None)
                seen = []
                for operation, arguments in operations:
                    if operation in {"open_binary", "inspect_managed_artifact"}:
                        arguments = {**arguments, "path": str(target)}
                    elif operation == "analyze_javascript_application":
                        arguments = {**arguments, "input_path": str(target)}
                    r = await service.call(row["id"], operation, arguments, None)
                    assert r["success"], json.dumps(r)[:2000]
                    seen.append(r)
                if name == ".NET":
                    methods = seen[-1]["result"]["structuredContent"]["result"]["methods"]
                    compute = next(m for m in methods if m["name"] == "Compute")
                    counts = compute["body"]["opcode_counts"]
                    assert all(counts.get(op) == 1 for op in ("ldc.i4.7", "mul", "ldc.i4.3", "add"))
                else:
                    assert "ANZU_STORE_V1" in json.dumps(seen)
                if name == "native PE":
                    assert "* 7 + 3" in json.dumps(seen[-1])
                store.write_report(store.load(row["id"]),
                                   [{"claim": ("Compute contains multiply/add and constants 7 and 3 in decoded CIL." if name == ".NET" else "The fixture storage marker ANZU_STORE_V1 appears in static inspection evidence."), "kind": "observation",
                                     "evidence_ids": [e["id"] for e in seen]}],
                                   ["Only fixture-specific static behavior was checked."])
                await service.close(row["id"], None)
                results.append({"case": name, "passed": True, "investigation_id": row["id"]})
            except Exception as exc:
                results.append({"case": name, "passed": False, "error": (type(exc).__name__ + ": " + str(exc))[:2000]})
        results.append(await verify_browser(service, p))
        if mobile:
            from app.policy.approval_grant import decide_approval_request
            row = await service.prepare(str(p / "fixture.apk"), "Observe the fixture label", [str(p)], None)
            args = {"package": "org.anzu.fixture", "activity": ".MainActivity", "steps": [{"kind": "wait", "milliseconds": 500}]}
            pending = await service.call(row["id"], "android_capture", args, None)
            assert pending["status"] == "pending_approval"
            # The --android invocation authorizes only this source-owned fixture scenario.
            grant = decide_approval_request(pending["pending_id"], decision="allow_once", origin_channel="api",
                                            actor="User-authorized source-owned desktop acceptance")["grant"]
            try:
                capture = await service.call(row["id"], "android_capture", args, None, grant["id"])
                assert capture["success"] and "ANZU_STORE_V1" in json.dumps(capture)
                results.append({"case": "Android runtime and approval", "passed": True, "investigation_id": row["id"]})
            except Exception as exc:
                results.append({"case": "Android runtime and approval", "passed": False, "error": str(exc)})
    finally:
        await service.shutdown()
    store.atomic_json(p / "acceptance.json", {"results": results})
    print(json.dumps(results, indent=2))
    return all(r["passed"] for r in results)


async def verify_browser(service, p):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import socket
    from playwright.async_api import async_playwright

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>ANZU_STORE_V1</h1></body></html>")
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        cdp_port = s.getsockname()[1]
    endpoint = f"http://127.0.0.1:{cdp_port}"
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=[f"--remote-debugging-port={cdp_port}"])
            try:
                page = await browser.new_page()
                await page.goto(origin)
                row = await service.prepare(endpoint, "Read the fixture heading", [], None, [origin])
                discovered = await service.call(row["id"], "list_browser_targets",
                                                 {"cdp_endpoint": endpoint, "allowed_origins": [origin]}, None)
                assert discovered["success"], json.dumps(discovered)
                payload = discovered["result"].get("structuredContent", {})
                # Resolve the exact advertised page ID; do not select other open tabs.
                targets = payload.get("result", {})
                if isinstance(targets, dict):
                    targets = targets.get("targets", [])
                selected = next(t for t in targets if t.get("url", "").startswith(origin))
                target_id = selected.get("target_id") or selected.get("id")
                observed = await service.call(row["id"], "inspect_web_page",
                    {"cdp_endpoint": endpoint, "allowed_origins": [origin],
                     "target_id": target_id, "include_accessibility_text": True}, None)
                assert observed["success"] and "ANZU_STORE_V1" in json.dumps(observed), json.dumps(observed)[:2000]
                await service.close(row["id"], None)
                return {"case": "Browser observation", "passed": True, "investigation_id": row["id"]}
            finally:
                await browser.close()
    except Exception as exc:
        return {"case": "Browser observation", "passed": False, "error": str(exc)[:3000]}
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--android", action="store_true", help="Build and run the known source-owned APK fixture with exact-action approval")
    args = parser.parse_args()
    output = Path.home() / ".anzu" / "acceptance" / "rfc0200"
    build_fixtures(output, args.android)
    sys.exit(0 if asyncio.run(verify(output, args.android)) else 1)
