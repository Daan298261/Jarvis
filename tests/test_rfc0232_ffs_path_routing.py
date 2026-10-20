"""RFC-0232 S1 repro: a local FFS/APK path plus a question must reach the RE tool
deterministically, and large inputs must never enter the model context.

Written xfail(strict=True) first (S1). Fix slices remove each marker:
  S2 — route + dump-wording tests (all twelve cases)
  S3 — ingest dispatch + overflow test
The plain-path negatives are live from S1 and must stay green in every slice.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.loop import AGENT
from app.agent.planning import route_request
from app.agent.tool_exposure import tool_names_for
from app.providers.base import ChatResult
from app.reverse_engineering import store
from tests.test_verification_loop import ScriptedProvider, _finished, _tool

# Hard per-call context budget the fix enforces (RFC-0232 §Context budget).
CONTEXT_BUDGET_CHARS = 24_000

# Taco's Windows / UNC / POSIX forms (S1 table).
TACO_PROMPTS = [
    r"D:\cases\x\ffs what apps are installed and when was WhatsApp last used?",
    r"Here is the Android FFS root D:\cases\x\ffs and the full extraction D:\cases\x\extraction.zip. Which accounts are on the phone?",
    r"\\NAS\cases\x\ffs - which messaging apps have databases?",
    r"//nas/cases/x/ffs which messaging apps have databases?",
    r"/mnt/cases/x/ffs which apps are installed?",
    r"Analyze D:\cases\x\app.apk: what servers does it talk to?",
]

# D2: dump wordings that must all route (S1 table ids). The last two are Taco's own phrasing
# (D2 2026-10-20); neither path ends in ffs/dump/extraction, so only the new rule-2 wording
# alternatives (`android file system`, bare `file system` + absolute path) can route them.
DUMP_WORDING_PROMPTS = [
    pytest.param(r"D:\cases\x\ffs what apps are installed?", id="ffs"),
    pytest.param(r"D:\cases\x\extraction which accounts are on the phone?", id="extraction"),
    pytest.param(r"D:\cases\x\dump what databases are present?", id="dump"),
    pytest.param(
        r"D:\cases\x\phone full file system dump — which messaging apps have databases?",
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


# Live negatives (not xfail): a path with a plain or coding question must keep routing normally.
# They pass on development today; S2's narrowed detector must keep them green (RFC-0232 rule 2).
PLAIN_PATH_PROMPTS = [
    pytest.param(r"C:\code\etl what does the extraction step do?", id="etl-extraction-step"),
    pytest.param(r"C:\Users\taco\proj ffs why does the build fail?", id="ffs-interjection"),
]

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


def _call_chars(call: dict) -> int:
    return sum(len(getattr(m, "content", "") or "") for m in call["messages"])


@pytest.mark.xfail(strict=True, reason="RFC-0232 S1 repro: path+question is not routed to the RE tool (fixed in S2)")
@pytest.mark.parametrize("prompt", TACO_PROMPTS)
def test_path_plus_question_routes_to_reverse_engineering(prompt):
    route = route_request(prompt)
    assert route.kind == "managed_task"
    assert route.task_class == "reverse engineering"
    assert "reverse_engineer" in tool_names_for(route.task_class, prompt=prompt)


@pytest.mark.xfail(strict=True, reason="RFC-0232 S1 repro: dump wordings do not route (fixed in S2)")
@pytest.mark.parametrize("prompt", DUMP_WORDING_PROMPTS)
def test_dump_wordings_route_to_reverse_engineering(prompt):
    route = route_request(prompt)
    assert route.kind == "managed_task"
    assert route.task_class == "reverse engineering"
    assert "reverse_engineer" in tool_names_for(route.task_class, prompt=prompt)


@pytest.mark.parametrize("prompt", PLAIN_PATH_PROMPTS)
def test_path_with_plain_or_coding_question_does_not_route_to_re(prompt):
    route = route_request(prompt)
    assert route.task_class != "reverse engineering", route


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
