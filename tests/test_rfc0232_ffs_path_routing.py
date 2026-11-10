"""RFC-0232 S1 repro: a local FFS/APK path plus RE intent must reach the RE tool
deterministically, a path with a plain or coding question must route normally, and large
inputs must never enter the model context.

Detection is two-stage (RFC-0232 §Deterministic path + RE-intent router):
  (a) a cheap wording-plus-path prefilter: EXPLICIT owner wording skips only the dump-marker
      requirement (it still runs the allow-list gate and the source veto); a WEAK match must pass
  (b) the on-disk probe ``planning.probe_dump_target`` (allow-list first, stat only, bounded).
The probe and ``re_intent_match`` always read the owner's allow-list from settings and never pass
``None`` to ``store.admit_allowed_target``; an empty list admits nothing.

Written xfail(strict=True) first (S1). Fix slices remove each marker:
  S2: path-form, dump-wording, explicit-wording and on-disk probe tests
  S3: ingest dispatch + overflow test
The live tests (no marker) pass on development today and must stay green in every slice.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.loop import AGENT
from app.agent.planning import route_request
from app.agent.tool_exposure import tool_names_for
from app.providers.base import ChatResult
from app.reverse_engineering import store
from tests.test_verification_loop import ScriptedProvider, _finished, _tool

# Hard per-call context budget the fix enforces (RFC-0232 §Context budget).
CONTEXT_BUDGET_CHARS = 24_000

# Taco's Windows / UNC / POSIX / .apk forms (S1 table). Every one is a WEAK prefilter match, so these
# tests stand the probe in with a "dump" verdict: they pin path parsing and route wiring for path
# forms that cannot exist on the CI runner. The real probe is exercised on disk below.
TACO_PROMPTS = [
    r"D:\cases\x\ffs what apps are installed and when was WhatsApp last used?",
    r"Here is the Android FFS root D:\cases\x\ffs and the full extraction D:\cases\x\extraction.zip. Which accounts are on the phone?",
    r"\\NAS\cases\x\ffs - which messaging apps have databases?",
    r"//nas/cases/x/ffs which messaging apps have databases?",
    r"/mnt/cases/x/ffs which apps are installed?",
    r"Analyze D:\cases\x\app.apk: what servers does it talk to?",
]

# D2: dump wordings that must all route (S1 table ids); all WEAK matches (a bare "full file system
# dump" is weak; only "full file system extraction" is explicit), probe stood in as "dump".
DUMP_WORDING_PROMPTS = [
    pytest.param(r"D:\cases\x\ffs what apps are installed?", id="ffs"),
    pytest.param(r"D:\cases\x\extraction which accounts are on the phone?", id="extraction"),
    pytest.param(r"D:\cases\x\dump what databases are present?", id="dump"),
    pytest.param(
        r"D:\cases\x\phone full file system dump - which messaging apps have databases?",
        id="full-file-system-dump",
    ),
    pytest.param(
        r"D:\cases\x\phone this is the root of an Android file system - which accounts are on the phone?",
        id="android-file-system",
    ),
    pytest.param(
        r"Here is the file system at D:\cases\x\phone. What apps are installed?",
        id="file-system-abs-path",
    ),
]

# EXPLICIT owner wording is exactly the four CoS phrases: "reverse engineer", "full FFS",
# "full file system extraction" and "extraction of my phone" (strict literal). It routes without a
# dump marker; the probe still runs with require_marker=False for the allow-list gate and the source
# veto. "FFS of my ...", "decompile"/"disassemble" and .apk paths are WEAK and need a "dump" verdict.
# ("reverse engineer" is also pinned live by test_reverse_engineer_wording_still_routes below.)
EXPLICIT_PROMPTS = [
    pytest.param(r"D:\cases\x\p1 is a full FFS of my Pixel, which apps?", id="full-ffs"),
    pytest.param(r"D:\cases\x\p1 is a full file system extraction, which accounts are on it?", id="full-file-system-extraction"),
    pytest.param(r"D:\cases\x\p1 is the extraction of my phone. Which messaging apps are there?", id="extraction-of-my-phone"),
]

# Live negatives: a path with a plain or coding question routes normally (CoS + D2 rounds 2-3).
PLAIN_PATH_PROMPTS = [
    pytest.param(r"C:\code\etl what does the extraction step do?", id="etl-extraction-step"),
    pytest.param(r"C:\Users\taco\proj ffs why does the build fail?", id="ffs-interjection"),
    pytest.param(r"D:\src\app how does the Android filesystem API work here?", id="android-filesystem-api"),
    pytest.param(r"C:\code\shop which phone image is shown on the product page?", id="phone-image"),
    pytest.param(r"C:\code\cam what does the device image upload do?", id="device-image"),
    pytest.param(r"C:\code\kernel where is the device dump handler?", id="device-dump-handler"),
    pytest.param(r"C:\code\fs what does the file system dump command in /usr/bin do?", id="file-system-dump-command"),
    pytest.param(r"C:\code\aosp\system\framework what does this module do?", id="aosp-system-framework"),
    pytest.param(r"C:\code\launcher\data\app which class handles install?", id="launcher-data-app"),
    # D2 round 4: none of these is one of the four owner phrases, so none is explicit.
    pytest.param(r"C:\code\tool what does the forensic image parser do?", id="forensic-image-parser"),
    pytest.param(r"C:\code\backup where is the full file system image backup written?", id="full-file-system-image-backup"),
    pytest.param(r"C:\code\mdm how is the extraction of the device id done?", id="extraction-of-the-device-id"),
    pytest.param(r"C:\code\agent what does the device extraction module do?", id="device-extraction-module"),
    pytest.param(r"C:\Users\taco\proj ffs of the tests fail again, why?", id="ffs-of-the-tests"),
    # D2 round 5: a hyphen is not a word boundary, so neither owner phrase matches here.
    pytest.param(r"C:\code\contacts how do I fix the extraction of my phone-number parser?", id="phone-number-parser"),
    pytest.param(r"C:\code\retests full FFS-like test fixture, what does it do?", id="ffs-like-fixture"),
]


def _dump_verdict(monkeypatch):
    """Stand in for the S2 probe (it does not exist yet; raising=False)."""
    monkeypatch.setattr(
        "app.agent.planning.probe_dump_target",
        lambda target, allowed=None, *, require_marker=True: SimpleNamespace(verdict="dump", evidence="test stand-in"),
        raising=False,
    )


def _no_marker_probe(monkeypatch) -> list[bool]:
    """Explicit wording: the probe runs only without the marker requirement (admit + stat + veto)."""
    calls: list[bool] = []

    def present(target, allowed=None, *, require_marker=True):
        calls.append(require_marker)
        if require_marker:
            raise AssertionError("explicit wording must not require a dump marker")
        return SimpleNamespace(verdict="present", evidence="test stand-in")

    monkeypatch.setattr("app.agent.planning.probe_dump_target", present, raising=False)
    return calls


def _routes_to_re(prompt: str) -> None:
    route = route_request(prompt)
    assert route.kind == "managed_task"
    assert route.task_class == "reverse engineering"
    assert "reverse_engineer" in tool_names_for(route.task_class, prompt=prompt)


# ----- on-disk fixtures (tmp_path; jarvis_env allows tmp_path) --------------------------

def _fake_android_ffs(root: Path, files: int = 3000) -> Path:
    ffs = root / "ffs"
    (ffs / "system").mkdir(parents=True)
    (ffs / "system" / "build.prop").write_text("ro.build.version.release=14\n", encoding="utf-8")
    apps = ffs / "data" / "data"
    apps.mkdir(parents=True)
    for i in range(files):
        pkg = apps / f"com.example.app{i:05d}"
        pkg.mkdir()
        (pkg / "shared_prefs.xml").write_text("<map/>" * 40, encoding="utf-8")
    (ffs / "data" / "system_ce").mkdir(parents=True)
    (ffs / "data" / "system_ce" / "accounts_ce.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 4096)
    return ffs


def _dump_android_full(root: Path) -> Path:
    return _fake_android_ffs(root, files=3)


def _dump_data_only(root: Path) -> Path:
    d = root / "pixel_partial"
    (d / "data" / "data" / "com.whatsapp" / "databases").mkdir(parents=True)
    return d


def _dump_sdcard_only(root: Path) -> Path:
    d = root / "pixel_sdcard"
    (d / "sdcard" / "Android" / "data").mkdir(parents=True)
    (d / "sdcard" / "DCIM").mkdir(parents=True)
    return d


def _dump_tar(root: Path) -> Path:
    f = root / "p1_ffs.tar"
    f.write_bytes(b"\x00" * 1024)
    return f


def _dump_zip(root: Path) -> Path:
    f = root / "p1_ffs.zip"
    f.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    return f


ON_DISK_DUMPS = [
    pytest.param(_dump_android_full, "{p} this is the root of an Android file system - which apps are installed?", id="android-full"),
    pytest.param(_dump_data_only, "{p} this is the root of an Android file system - which apps are installed?", id="data-only"),
    pytest.param(_dump_sdcard_only, "{p} this is an Android file system pull - what photos are on it?", id="sdcard-only"),
    pytest.param(_dump_tar, "{p} which apps are installed?", id="ffs-tar"),
    pytest.param(_dump_zip, "{p} which apps are installed?", id="ffs-zip"),
]


def _fake_aosp_tree(root: Path) -> Path:
    aosp = root / "aosp"
    for rel in (".repo/manifests", "build/make", "system/core", "data/data"):
        (aosp / rel).mkdir(parents=True)
    (aosp / "Android.bp").write_text("// soong\n", encoding="utf-8")
    (aosp / "system" / "build.prop").write_text("ro.build.version.release=14\n", encoding="utf-8")
    return aosp


def _call_chars(call: dict) -> int:
    return sum(len(getattr(m, "content", "") or "") for m in call["messages"])


# ----- xfail (flipped by S2) ------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="RFC-0232 S1 repro: path+question is not routed to the RE tool (fixed in S2)")
@pytest.mark.parametrize("prompt", TACO_PROMPTS)
def test_path_plus_question_routes_to_reverse_engineering(prompt, monkeypatch):
    _dump_verdict(monkeypatch)
    _routes_to_re(prompt)


@pytest.mark.xfail(strict=True, reason="RFC-0232 S1 repro: dump wordings do not route (fixed in S2)")
@pytest.mark.parametrize("prompt", DUMP_WORDING_PROMPTS)
def test_dump_wordings_route_to_reverse_engineering(prompt, monkeypatch):
    _dump_verdict(monkeypatch)
    _routes_to_re(prompt)


@pytest.mark.xfail(strict=True, reason="RFC-0232 S1 repro: explicit dump wording does not route (fixed in S2)")
@pytest.mark.parametrize("prompt", EXPLICIT_PROMPTS)
def test_explicit_wording_routes_without_marker(prompt, monkeypatch):
    calls = _no_marker_probe(monkeypatch)
    _routes_to_re(prompt)
    assert calls and not any(calls), calls


@pytest.mark.xfail(strict=True, reason="RFC-0232 S1 repro: on-disk dumps are not detected (fixed in S2)")
@pytest.mark.parametrize(("make", "template"), ON_DISK_DUMPS)
def test_on_disk_dump_routes_after_probe(make, template, jarvis_env):
    target = make(jarvis_env["tmp"])
    _routes_to_re(template.format(p=target))


# ----- live (pass today; every slice keeps them green) ----------------------------------

@pytest.mark.parametrize("prompt", PLAIN_PATH_PROMPTS)
def test_path_with_plain_or_coding_question_does_not_route_to_re(prompt):
    route = route_request(prompt)
    assert route.task_class != "reverse engineering", route


def test_reverse_engineer_wording_still_routes():
    _routes_to_re(r"reverse engineer D:\cases\x\ffs")


def test_aosp_source_tree_routes_normally(jarvis_env):
    aosp = _fake_aosp_tree(jarvis_env["tmp"])
    route = route_request(f"{aosp} this is the root of an Android file system - what does init do?")
    assert route.task_class != "reverse engineering", route


def _spy_probes(monkeypatch, outside: Path) -> list[str]:
    probed: list[str] = []
    real_stat, real_exists = os.stat, Path.exists

    def spy_stat(path, *a, **k):
        if str(outside) in os.fspath(path):
            probed.append(os.fspath(path))
        return real_stat(path, *a, **k)

    def spy_exists(self, *a, **k):
        if str(outside) in str(self):
            probed.append(str(self))
        return real_exists(self, *a, **k)

    monkeypatch.setattr(os, "stat", spy_stat)
    monkeypatch.setattr(Path, "exists", spy_exists)
    return probed


def test_outside_path_with_markers_is_never_probed(jarvis_env, tmp_path_factory, monkeypatch):
    outside = _dump_android_full(tmp_path_factory.mktemp("outside_allowed"))
    probed = _spy_probes(monkeypatch, outside)
    route = route_request(f"{outside} this is the root of an Android file system - which apps are installed?")
    assert probed == [], probed  # allow-list first: no existence oracle (store.admit_allowed_target)
    assert route.task_class != "reverse engineering", route


def test_empty_allow_list_refuses_outside_target_without_stat(jarvis_env, tmp_path_factory, monkeypatch):
    """D1 via CoS: the probe reads the owner's list from settings and never passes None to the gate.

    With an empty settings list nothing is admitted, so the target is refused and never stat'd.
    """
    outside = _dump_android_full(tmp_path_factory.mktemp("outside_empty_list"))
    jarvis_env["settings"].allowed_directories = []
    monkeypatch.setattr("app.agent.planning.load_settings", lambda: jarvis_env["settings"], raising=False)
    probed = _spy_probes(monkeypatch, outside)
    route = route_request(f"{outside} this is the root of an Android file system - which apps are installed?")
    assert probed == [], probed
    assert route.task_class != "reverse engineering", route


# ----- xfail (flipped by S3) ------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="RFC-0232 S1 repro: FFS root goes to the model, not ingest (fixed in S3)")
async def test_ffs_path_plus_question_calls_ingest_without_overflow(jarvis_env):
    ffs = _fake_android_ffs(jarvis_env["tmp"])
    # What the 9B does today on the fallback path: list the dump, then search members.
    provider = ScriptedProvider(
        [
            ChatResult(content="END STATE: answer\nACCEPTANCE CRITERIA:\n- answered\nPLAN:\n1. look"),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "list", "path": str(ffs / "data" / "data")}, "c1")]),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "search", "path": str(ffs), "pattern": "*.xml"}, "c2")]),
            ChatResult(content="Done."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(f"{ffs} which apps are installed?", autonomy="autonomous", profile="fast")
    await _finished(created.id)
    rows = store.list_rows(created.id)
    assert any(row.get("kind") == "ffs" for row in rows), "the RE ingest was never called"
    assert all(_call_chars(call) <= CONTEXT_BUDGET_CHARS for call in provider.calls), [
        _call_chars(c) for c in provider.calls
    ]
    offered = {t["function"]["name"] for c in provider.calls for t in (c["tools"] or [])}
    assert "reverse_engineer" in offered or not provider.calls[1:]
