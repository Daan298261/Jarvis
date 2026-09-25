"""Shared fixtures for byte-identical System-One provider benchmarks (RFC-0171)."""

from __future__ import annotations

from typing import Any

# Byte-identical Anzu fixtures — same state/questions for rules / Laya / Jev / generative.
FIXTURE_TOOL_SELECT: dict[str, Any] = {
    "decision_class": "tool_selection",
    "state": {
        "user_message": "please read the file notes.txt from disk",
        "candidate_tools": ["filesystem", "git", "browser"],
    },
    "questions": {
        "tool_select": {
            "type": "choice",
            "choices": ["filesystem", "git", "browser", "none"],
            "question": "Which retrieved tool should this turn use?",
        }
    },
}

FIXTURE_MEMORY: dict[str, Any] = {
    "decision_class": "memory_relevance",
    "state": {
        "user_message": "what did we decide about the vault router",
        "excerpts": {
            "memory_0": "Decisions/vault-router.md: use _Config/router.md for orientation",
            "memory_1": "Projects/gardening.md: water the plants twice a week",
        },
    },
    "questions": {
        "memory_0": {
            "type": "score",
            "question": "Relevance of vault router decision",
            "min": 0.0,
            "max": 1.0,
        },
        "memory_1": {
            "type": "score",
            "question": "Relevance of gardening note",
            "min": 0.0,
            "max": 1.0,
        },
    },
}

FIXTURE_ROUTING: dict[str, Any] = {
    "decision_class": "persona_model_routing",
    "state": {
        "user_message": "hello there",
        "preferred_profile": "fast",
        "candidate_profiles": ["fast", "balanced", "quality"],
    },
    "questions": {
        "route_profile": {
            "type": "choice",
            "choices": ["fast", "balanced", "quality"],
            "question": "Which profile should handle this turn?",
        }
    },
}

FIXTURE_BROWSER: dict[str, Any] = {
    "decision_class": "browser_operation_target",
    "state": {
        "user_message": "click the search button",
        "suggested_operation": "CLICK",
        "suggested_target_id": "n3",
        "frame_id": "frame-1",
    },
    "questions": {
        "operation": {
            "type": "choice",
            "choices": ["CLICK", "TYPE_TEXT", "SCROLL", "NOOP"],
            "question": "Which operation?",
        },
        "target_id": {
            "type": "choice",
            "choices": ["n1", "n2", "n3", "none"],
            "question": "Which target?",
        },
        "done": {"type": "boolean", "question": "Done?"},
        "block": {"type": "boolean", "question": "Block?"},
    },
}

FIXTURE_APPROVAL: dict[str, Any] = {
    "decision_class": "approval_signal",
    "state": {
        "user_message": "delete everything",
        "policy_requires_approval": True,
        "policy_deny": False,
    },
    "questions": {
        "approval_needed": {
            "type": "noul",
            "question": "Needs Always/Allow/Deny popup?",
        }
    },
}


ALL_FIXTURES = (
    FIXTURE_TOOL_SELECT,
    FIXTURE_MEMORY,
    FIXTURE_ROUTING,
    FIXTURE_BROWSER,
    FIXTURE_APPROVAL,
)
