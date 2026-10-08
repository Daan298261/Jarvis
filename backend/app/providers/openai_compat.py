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

    async def chat(self, messages, tools=None, temperature=None, top_p=None, top_k=None,
                   max_tokens=None, thinking=None, extra=None):
        from . import local_qwen_text as text
        if text.eligible(messages, tools, thinking, extra) and await text.admitted(self):
            result = await self.client.completions.create(**text.arguments(
                self, messages, temperature, top_p, top_k, max_tokens, extra))
            from .completion_text import visible_completion_text
            content = visible_completion_text(result.choices[0].text)
            if not content:
                raise RuntimeError("Local Qwen text completion returned no visible answer")
            return ChatResult(content=content, usage=result.usage.model_dump() if result.usage else {})
        return await super().chat(messages, tools=tools, temperature=temperature, top_p=top_p,
                                  top_k=top_k, max_tokens=max_tokens, thinking=thinking, extra=extra)

    async def chat_stream(self, messages, *, temperature=None, top_p=None, top_k=None,
                          max_tokens=None, thinking=None, extra=None):
        from . import local_qwen_text as text
        if text.eligible(messages, None, thinking, extra) and await text.admitted(self):
            stream = await self.client.completions.create(stream=True, **text.arguments(
                self, messages, temperature, top_p, top_k, max_tokens, extra))
            yielded = False
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].text:
                    yielded = True
                    yield chunk.choices[0].text
            if not yielded:
                raise RuntimeError("Local Qwen text stream returned no visible answer")
            return
        async for delta in super().chat_stream(messages, temperature=temperature, top_p=top_p,
                                               top_k=top_k, max_tokens=max_tokens, thinking=thinking, extra=extra):
            yield delta
