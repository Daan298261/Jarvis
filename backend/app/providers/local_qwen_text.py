"""Verified local Qwen35 text-only non-thinking completion path.

Some LM Studio GGUF instances ignore chat-template thinking flags. Explicitly
close the thinking prefix for text-only requests; tools and vision keep chat API.
"""
import time
from urllib.parse import urlparse

import httpx


def eligible(messages, tools, thinking, extra):
    return (thinking is False and not tools and not (extra or {}).get("response_format")
            and bool(messages) and all(m.role in {"system", "user", "assistant"}
                                      and isinstance(m.content, str) and not m.tool_calls
                                      and "<|" not in m.content and "|>" not in m.content for m in messages))


def prompt(messages):
    return "".join(f"<|im_start|>{m.role}\n{m.content}<|im_end|>\n" for m in messages) + "<|im_start|>assistant\n<think>\n\n</think>\n\n"


async def admitted(provider):
    parsed = urlparse(provider.base_url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port != 1234:
        return False
    cached = getattr(provider, "_qwen_text_capability", None)
    if cached and time.monotonic() - cached[0] < 15:
        return cached[1]
    root = provider.base_url.removesuffix("/v1")
    url = root + "/api/v1/models"
    verified = False
    try:
        from ..policy.network_http import require_http_url_allowed
        require_http_url_allowed(url, tool="web_fetch")
        async with httpx.AsyncClient(timeout=.5) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {provider.api_key}"})
            response.raise_for_status()
            for model in response.json().get("models", []):
                if model.get("architecture") == "qwen35" and any(
                    row.get("id") == provider.model for row in model.get("loaded_instances", [])
                ):
                    verified = True
                    break
    except (httpx.HTTPError, ValueError, PermissionError):
        pass
    provider._qwen_text_capability = (time.monotonic(), verified)
    return verified


def arguments(provider, messages, temperature, top_p, top_k, max_tokens, extra):
    options = dict(extra or {})
    options.pop("chat_template_kwargs", None)
    options.pop("reasoning_budget", None)
    if top_k is not None:
        options["top_k"] = top_k
    result = dict(model=provider.model, prompt=prompt(messages),
                  max_tokens=max_tokens or 1024, stop=["<|im_end|>", "<|im_start|>", "<|endoftext|>"], extra_body=options)
    if temperature is not None:
        result["temperature"] = temperature
    if top_p is not None:
        result["top_p"] = top_p
    return result
