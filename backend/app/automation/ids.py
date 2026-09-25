from __future__ import annotations


def schedule_automation_id(schedule_id: str) -> str:
    return f"schedule:{schedule_id}"


def event_subscription_automation_id(subscription_id: str) -> str:
    return f"event-subscription:{subscription_id}"


def proactive_automation_id(parent_agent_id: str, action_id: str) -> str:
    return f"proactive:{parent_agent_id}:{action_id}"


def automation_actor_id(automation_id: str) -> str:
    return f"automation:{automation_id}"
