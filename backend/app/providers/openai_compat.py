from .base import ChatMessage, ChatResult, ModelProvider, parse_tool_arguments, to_openai_messages

__all__ = [
    "ChatMessage",
    "ChatResult",
    "ModelProvider",
    "OpenAICompatProvider",
    "parse_tool_arguments",
    "to_openai_messages",
]


class OpenAICompatProvider(ModelProvider):
    """Named alias for the default OpenAI-compatible provider (local llama.cpp or remote LAN)."""

    name = "openai-compat"
