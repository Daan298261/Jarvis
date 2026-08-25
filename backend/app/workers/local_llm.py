from __future__ import annotations

import os
from typing import Any

from ..config import AppSettings, load_settings


def local_openai_base_url(settings: AppSettings | None = None) -> str:
    current = settings or load_settings()
    return f"http://{current.inference.host}:{current.inference.port}/v1"


def local_openai_model(settings: AppSettings | None = None) -> str:
    current = settings or load_settings()
    return os.environ.get("JARVIS_LLM_MODEL") or current.inference.profile or "qwen"


def local_openai_env(settings: AppSettings | None = None) -> dict[str, str]:
    """Force optional workers onto Jarvis's local OpenAI-compatible server, never a cloud default."""
    current = settings or load_settings()
    base = local_openai_base_url(current)
    key = os.environ.get("JARVIS_LLM_API_KEY") or "local"
    model = local_openai_model(current)
    return {
        "LLM_BASE_URL": base,
        "LLM_API_BASE": base,
        "LLM_API_KEY": key,
        "LLM_MODEL": model,
        "OPENAI_BASE_URL": base,
        "OPENAI_API_BASE": base,
        "OPENAI_API_KEY": key,
        "OPENAI_API_HOST": base,
        "OPENAI_MODEL": model,
    }


def merge_local_env(settings: AppSettings | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(local_openai_env(settings))
    return env


def local_chat_openai(settings: AppSettings | None = None) -> Any:
    """Build an OpenAI-compatible chat client for optional Python SDKs."""
    current = settings or load_settings()
    base = local_openai_base_url(current)
    model = local_openai_model(current)
    key = os.environ.get("JARVIS_LLM_API_KEY") or "local"
    errors: list[str] = []
    for module_name, class_name in (
        ("browser_use.llm", "ChatOpenAI"),
        ("browser_use.llm.openai", "ChatOpenAI"),
        ("langchain_openai", "ChatOpenAI"),
    ):
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            try:
                return cls(model=model, base_url=base, api_key=key)
            except TypeError:
                return cls(model=model, openai_api_base=base, openai_api_key=key)
        except Exception as exc:
            errors.append(f"{module_name}.{class_name}: {exc}")
    raise RuntimeError("No local ChatOpenAI wrapper is available. " + " | ".join(errors))
