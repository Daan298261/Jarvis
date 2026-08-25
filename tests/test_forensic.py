from app.agent.forensic import is_professional_audit, professional_prompt_block
from app.agent.loop import AGENT
from app.providers.base import ChatResult
from tests.test_verification_loop import ScriptedProvider, _finished, _tool


def test_keyword_detection_does_not_need_the_settings_toggle():
    assert is_professional_audit("Analyze this malware sample from the IR case")
    assert is_professional_audit("Summarize the phishing kit artifacts")
    assert not is_professional_audit("Rename the downloads folder")


def test_settings_toggle_forces_the_mode():
    assert is_professional_audit("organize my desktop", professional_mode=True)
    block = professional_prompt_block("organize my desktop", professional_mode=True)
    assert "Forensic Audit Mode" in block
    assert "operational authorization" in block.lower()


def test_ordinary_prompts_get_no_audit_block():
    assert professional_prompt_block("write a unit test for filesystem.compare") == ""


async def test_forensic_prompt_is_injected_for_malware_analysis(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "report.txt"
    provider = ScriptedProvider(
        [
            ChatResult(
                content=(
                    "END STATE: report.txt exists\n"
                    "ACCEPTANCE CRITERIA:\n- file contains ANALYSIS\n"
                    "PLAN:\n1. write the report"
                )
            ),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "ANALYSIS", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Wrote the analysis."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified report.txt contains ANALYSIS."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Analyze this malware sample and write ANALYSIS to {target}.",
        autonomy="autonomous",
        profile="fast",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    system = provider.calls[0]["messages"][0].content
    assert "Forensic Audit Mode" in system
    assert "Do not refuse merely because the subject is sensitive" in system
