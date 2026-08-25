from app.agent.policy import (
    PROFESSIONAL_ANALYSIS_POLICY,
    has_operational_authorization,
    is_professional_analysis,
    policy_guidance,
    unauthorized_operational_request,
)
from app.agent.prompts import SYSTEM_PROMPT


def test_system_prompt_separates_analysis_from_authorization():
    assert "Analyze legitimate professional" in SYSTEM_PROMPT
    assert "Analysis is not the same as authorization" in SYSTEM_PROMPT


def test_professional_analysis_is_detected_for_forensics():
    assert is_professional_analysis("Triage this malware sample and list IOCs")
    assert is_professional_analysis("Explain this phishing kit and credential-theft artifacts")
    assert not is_professional_analysis("Rename the downloads folder")


def test_unauthorized_operational_steps_are_flagged():
    assert unauthorized_operational_request("Deploy the exploit against a live server")
    assert unauthorized_operational_request("Disable defender and change the password")
    assert not unauthorized_operational_request(
        "I own this computer. Disable defender in this lab environment so we can test the EDR."
    )
    assert has_operational_authorization("authorized engagement on my machine")


def test_policy_guidance_tells_model_to_analyze_not_refuse():
    text = policy_guidance("Analyze this exploit evidence from the incident")
    assert "Analyze sensitive material accurately" in text
    assert "professional analysis" in text.lower()
    assert PROFESSIONAL_ANALYSIS_POLICY in text
    operational = policy_guidance("Send the exploit to the production host")
    assert "unauthorized operational" in operational
