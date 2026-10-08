from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any

import psutil
from openai import APIStatusError

from ..config import AppSettings, load_settings, logs_dir
from ..persona.pack import compact_identity_instructions, inject_compact_identity_messages, persona_instructions
from ..providers.base import ChatMessage
from ..providers.openai_compat import OpenAICompatProvider
from .backends import (
    InferenceBackend,
    LLAMA_CPP_ALIASES,
    LMSTUDIO_ALIASES,
    normalize_chat_messages,
    probe_remote_server,
    resolve_backend,
)
from .context_window import (
    clamp_n_keep,
    is_n_keep_overflow,
    n_keep_for_messages,
    n_keep_overflow_message,
    parse_n_keep_overflow,
)
from .inference_prompt import sanitize_messages_for_inference
from .profiles import (
    PROFILES,
    ModelProfile,
    declared_profiles,
    profile_from_gguf_path,
    profile_gguf,
    qwen38_9b_profile,
    resolve_mmproj,
    resolve_profile,
)
from .prompt_budget import (
    ModelCapacityExceeded,
    estimate_prompt_tokens,
    is_context_overflow,
    prepare_inference,
    recover_context_after_overflow,
)
from .request_lease import RequestLease
from .stream_deadlines import compute_chat_call_deadline_ms, compute_chat_stream_deadlines


def resolve_vision(settings: AppSettings, requested: bool | None = None) -> bool:
    """Whether this start should attach mmproj.

    Idle loads pass requested=None. Lazy mode never attaches until a vision
    request sets requested=True. Settings.vision_mode "always" keeps the
    projector after a request; it still does not attach at idle load.
    """
    mode = str(getattr(settings.inference, "vision_mode", None) or "lazy").strip().lower()
    flag = settings.inference.vision
    if isinstance(flag, str) and flag.strip():
        mode = flag.strip().lower()
    if mode in {"off", "never", "disabled"}:
        return False
    return bool(requested)


@dataclass
class InferenceState:
    loaded: bool = False
    loading: bool = False
    profile: str = "balanced"
    quant: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    vision_loaded: bool = False
    vision_mode: str = "lazy"
    backend: str = "llama.cpp"
    manages_process: bool = True
    host: str = "127.0.0.1"
    port: int = 8088
    context_size: int = 16384
    server_n_ctx: int = 0
    gpu_layers: str = "fit"
    flash_attn: str = "auto"
    pid: int | None = None
    load_time_seconds: float | None = None
    prompt_tps: float | None = None
    generation_tps: float | None = None
    vram_used_mib: int | None = None
    ram_used_gb: float | None = None
    last_error: str = ""
    llama_version: str = ""
    vision: bool = False
    family: str = ""
    alias: str = ""
    thinking_mode: str = ""
    advertised_models: list[str] | None = None
    health_path: str = ""
    remote_model: str = ""
    gguf_path: str = ""


def _with_context(profile: ModelProfile, context_size: int) -> ModelProfile:
    return replace(profile, context_size=context_size)


def _default_load_context(profile: ModelProfile) -> int:
    cap = int(profile.context_size or 16384)
    if profile.name == "fast":
        return min(8192, cap)
    return min(32768, cap)


def _profile_from_gguf_or_name(
    settings: AppSettings,
    profile_name: str | None,
    *,
    gguf_path: str | None = None,
    stored_gguf: str = "",
    context_size: int | None = None,
) -> ModelProfile:
    requested = (profile_name or "").strip()
    path = str(gguf_path or "").strip()
    if not path:
        if requested in PROFILES:
            path = ""
        else:
            path = str(stored_gguf or "").strip()
    if path:
        profile = profile_from_gguf_path(Path(path))
    else:
        profile = resolve_profile(requested or settings.inference.profile)
    if context_size:
        profile = _with_context(profile, int(context_size))
    return profile


def _message_text(message: ChatMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(message.content, ensure_ascii=False)


def _trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 48:
        return text[:limit]
    head = max(24, int(limit * 0.62))
    tail = max(12, limit - head - 30)
    return text[:head] + "\n[Earlier context trimmed]\n" + text[-tail:]


def _message_with_content(message: ChatMessage, content: str) -> ChatMessage:
    """Trim display content without breaking an OpenAI tool-call transcript."""
    return ChatMessage(
        role=message.role,
        content=content,
        name=message.name,
        tool_call_id=message.tool_call_id,
        tool_calls=message.tool_calls,
        reasoning_content=message.reasoning_content,
    )


def fit_messages_to_context(
    messages: list[ChatMessage],
    *,
    context_size: int,
    max_tokens: int | None,
    tool_schema_chars: int = 0,
) -> list[ChatMessage]:
    """Keep a request below the active server context before llama.cpp rejects it.

    The runtime may expose less context than a model's nominal cap (for
    example, a 4K LM Studio server). Use a deliberately conservative two
    characters/token estimate, reserve output/template headroom, retain the
    first system message and newest user turn, then discard oldest history.
    """
    limit = int(context_size or 0)
    if limit <= 0:
        return messages
    completion_reserve = max(256, min(int(max_tokens or 1024), max(256, limit // 2)))
    prompt_chars = max(768, (limit - completion_reserve - 256) * 2)
    message_budget = max(512, prompt_chars - max(0, tool_schema_chars))
    if sum(len(_message_text(message)) for message in messages) <= message_budget:
        return messages

    system = next((message for message in messages if message.role == "system"), None)
    non_system = [message for message in messages if message.role != "system"]
    kept: list[ChatMessage] = []
    used = 0
    if system is not None:
        # Prompt may still include this-turn guidance; n_keep pins identity only.
        system_limit = max(256, int(message_budget * 0.55))
        text = _trim_text(_message_text(system), system_limit)
        kept.append(_message_with_content(system, text))
        used += len(text)

    tail: list[ChatMessage] = []
    for message in reversed(non_system):
        remaining = message_budget - used
        if remaining <= 0:
            break
        text = _message_text(message)
        # Always preserve the latest turn, even when the system block was long.
        if not tail or len(text) <= remaining:
            clipped = _trim_text(text, max(96, remaining))
            tail.append(_message_with_content(message, clipped))
            used += len(clipped)
        else:
            break
    ordered_tail = list(reversed(tail))
    # A tool response cannot begin a retained OpenAI transcript: its matching
    # assistant tool call may have been discarded with older history.
    while ordered_tail and ordered_tail[0].role == "tool":
        ordered_tail.pop(0)
    return [*kept, *ordered_tail]


def fit_tools_to_context(
    tools: list[dict[str, Any]] | None,
    *,
    context_size: int,
    max_tokens: int | None,
) -> list[dict[str, Any]] | None:
    """Avoid serialising a tool catalog larger than a small server can hold."""
    if not tools:
        return tools
    limit = int(context_size or 0)
    if limit <= 0:
        return tools
    reserve = max(256, min(int(max_tokens or 1024), max(256, limit // 2)))
    char_budget = max(512, int((limit - reserve - 256) * 2 * 0.55))
    kept: list[dict[str, Any]] = []
    used = 0
    for tool in tools:
        size = len(json.dumps(tool, ensure_ascii=False))
        if kept and used + size > char_budget:
            continue
        if size > char_budget:
            continue
        kept.append(tool)
        used += size
    return kept


class InferenceManager:
    """Owns model lifecycle. Process control is delegated to an InferenceBackend."""

    def __init__(self) -> None:
        self.state = InferenceState()
        self.backend: InferenceBackend | None = None
        self._lock = asyncio.Lock()
        self._request_lease = RequestLease()
        self.provider: OpenAICompatProvider | None = None

    def _active_profile(
        self,
        settings: AppSettings,
        profile_name: str | None = None,
        *,
        gguf_path: str | None = None,
        context_size: int | None = None,
    ) -> ModelProfile:
        return _profile_from_gguf_or_name(
            settings,
            profile_name or self.state.profile,
            gguf_path=gguf_path,
            stored_gguf=self.state.gguf_path,
            context_size=context_size,
        )

    def base_url(self, settings: AppSettings) -> str:
        return f"http://{settings.inference.host}:{settings.inference.port}/v1"

    def provider_model(self, settings: AppSettings, advertised: list[str] | None = None) -> str:
        chosen = (settings.inference.remote_model or "").strip()
        if chosen:
            return chosen
        if advertised:
            return advertised[0]
        profile = self._active_profile(settings)
        return profile.alias or "Qwen3.5-9B"

    def provider_api_key(self, settings: AppSettings) -> str:
        return (settings.inference.api_key or "").strip() or "local"

    def _make_provider(self, settings: AppSettings, advertised: list[str] | None = None) -> OpenAICompatProvider:
        return OpenAICompatProvider(
            self.base_url(settings),
            api_key=self.provider_api_key(settings),
            model=self.provider_model(settings, advertised),
        )

    def prepare_chat_messages(
        self,
        messages: list[Any],
        *,
        max_tokens: int | None = None,
        tool_schema_chars: int = 0,
    ) -> list[ChatMessage]:
        """Normalize message order before llama.cpp / Qwen chat template rendering."""
        typed = [
            message if isinstance(message, ChatMessage) else ChatMessage(role="user", content=str(message))
            for message in messages
        ]
        with_persona = inject_compact_identity_messages(typed)
        normalized = normalize_chat_messages(with_persona)
        return fit_messages_to_context(
            normalized,
            context_size=self.live_context_size(),
            max_tokens=max_tokens,
            tool_schema_chars=tool_schema_chars,
        )

    def live_context_size(self) -> int:
        """The window the loaded server actually has, never an inflated profile cap."""
        live = int(self.state.server_n_ctx or 0)
        claimed = int(self.state.context_size or 0)
        if live > 0 and claimed > 0:
            return min(live, claimed)
        return live or claimed

    def adopt_server_n_ctx(self, n_ctx: int) -> int:
        """Record the live slot size and drop any oversized Jarvis-side window."""
        live = int(n_ctx or 0)
        if live <= 0:
            return self.live_context_size()
        self.state.server_n_ctx = live
        current = int(self.state.context_size or 0)
        if current <= 0 or current > live:
            self.state.context_size = live
        return self.live_context_size()

    def _supports_n_keep(self) -> bool:
        name = (self.state.backend or "").strip().lower()
        if name in LLAMA_CPP_ALIASES or name in LMSTUDIO_ALIASES:
            return True
        return (self.state.health_path or "") == "/health"

    def _with_n_keep(
        self,
        extra: dict[str, Any] | None,
        messages: list[ChatMessage],
        max_tokens: int | None,
    ) -> dict[str, Any]:
        payload = dict(extra or {})
        n_ctx = self.live_context_size()
        if n_ctx <= 0:
            return payload
        requested = payload.get("n_keep")
        if requested is None and not self._supports_n_keep():
            return payload
        identity = compact_identity_instructions()
        if requested is None:
            payload["n_keep"] = n_keep_for_messages(
                messages,
                n_ctx,
                max_tokens=max_tokens,
                identity_text=identity,
            )
        else:
            raw = int(requested)
            if raw < 0:
                raw = n_keep_for_messages(
                    messages,
                    n_ctx,
                    max_tokens=max_tokens,
                    identity_text=identity,
                )
            payload["n_keep"] = clamp_n_keep(raw, n_ctx, max_tokens=max_tokens)
        keep = int(payload.get("n_keep") or 0)
        if keep >= n_ctx:
            payload["n_keep"] = clamp_n_keep(keep, n_ctx, max_tokens=max_tokens)
            keep = int(payload["n_keep"])
        if keep >= n_ctx:
            raise RuntimeError(n_keep_overflow_message(keep, n_ctx))
        return payload

    def _adopt_n_keep_overflow(self, exc: BaseException) -> bool:
        parsed = parse_n_keep_overflow(getattr(exc, "body", None)) or parse_n_keep_overflow(exc)
        if not parsed:
            return False
        _n_keep, n_ctx = parsed
        self.adopt_server_n_ctx(n_ctx)
        return True

    async def chat(
        self,
        messages: list[Any],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
        extra: dict[str, Any] | None = None,
        settings: AppSettings | None = None,
        working_state_block: str | None = None,
    ):
        if not self.provider:
            raise RuntimeError("Inference model is not loaded")
        async with self._request_lease.shared():
            return await self._chat_holding_lease(
                messages,
                tools=tools,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                max_tokens=max_tokens,
                thinking=thinking,
                extra=extra,
                settings=settings,
                working_state_block=working_state_block,
            )

    async def _chat_holding_lease(
        self,
        messages: list[Any],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
        extra: dict[str, Any] | None = None,
        settings: AppSettings | None = None,
        working_state_block: str | None = None,
    ):
        app_settings = settings or load_settings()
        profile = self._active_profile(app_settings)
        typed = [
            message if isinstance(message, ChatMessage) else ChatMessage(role="user", content=str(message))
            for message in messages
        ]
        typed = sanitize_messages_for_inference(typed)
        overflow_retries = 0
        while True:
            fitted_tools = fit_tools_to_context(
                tools,
                context_size=self.live_context_size(),
                max_tokens=max_tokens,
            )
            try:
                preflight = await prepare_inference(
                    typed,
                    fitted_tools,
                    profile,
                    max_tokens,
                    app_settings,
                    manager=self,
                    working_state_block=working_state_block,
                )
            except ModelCapacityExceeded:
                if overflow_retries >= 2:
                    raise
                overflow_retries += 1
                tool_schema_chars = len(json.dumps(fitted_tools, ensure_ascii=False)) if fitted_tools else 0
                shrunk = self.prepare_chat_messages(
                    typed,
                    max_tokens=max_tokens,
                    tool_schema_chars=tool_schema_chars,
                )
                if shrunk is not typed:
                    typed = shrunk
                    continue
                typed, fitted_tools, recovered = await recover_context_after_overflow(
                    typed,
                    fitted_tools,
                    profile,
                    max_tokens,
                    app_settings,
                    manager=self,
                    working_state_block=working_state_block,
                )
                if recovered:
                    continue
                raise
            typed = preflight.messages
            fitted_tools = fit_tools_to_context(
                fitted_tools,
                context_size=self.live_context_size(),
                max_tokens=max_tokens,
            )
            tool_schema_chars = len(json.dumps(fitted_tools, ensure_ascii=False)) if fitted_tools else 0
            prepared = self.prepare_chat_messages(
                typed,
                max_tokens=max_tokens,
                tool_schema_chars=tool_schema_chars,
            )
            extra_payload = self._with_n_keep(extra, prepared, max_tokens)
            try:
                return await self.provider.chat(
                    prepared,
                    tools=fitted_tools,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    max_tokens=max_tokens,
                    thinking=thinking,
                    extra=extra_payload,
                    **self._chat_call_budget(app_settings, prepared),
                )
            except APIStatusError as exc:
                if is_n_keep_overflow(getattr(exc, "body", None)) or is_n_keep_overflow(exc):
                    if not self._adopt_n_keep_overflow(exc):
                        raise
                    fitted_tools = fit_tools_to_context(
                        tools,
                        context_size=self.live_context_size(),
                        max_tokens=max_tokens,
                    )
                    tool_schema_chars = len(json.dumps(fitted_tools, ensure_ascii=False)) if fitted_tools else 0
                    prepared = self.prepare_chat_messages(
                        typed,
                        max_tokens=max_tokens,
                        tool_schema_chars=tool_schema_chars,
                    )
                    extra_payload = self._with_n_keep(extra, prepared, max_tokens)
                    n_ctx = self.live_context_size()
                    keep = int(extra_payload.get("n_keep") or 0)
                    if n_ctx > 0 and keep >= n_ctx:
                        raise RuntimeError(n_keep_overflow_message(keep, n_ctx)) from exc
                    return await self.provider.chat(
                        prepared,
                        tools=fitted_tools,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        max_tokens=max_tokens,
                        thinking=thinking,
                        extra=extra_payload,
                        **self._chat_call_budget(app_settings, prepared),
                    )
                if is_context_overflow(exc) and overflow_retries < 1:
                    overflow_retries += 1
                    typed, fitted_tools, recovered = await recover_context_after_overflow(
                        typed,
                        fitted_tools,
                        profile,
                        max_tokens,
                        app_settings,
                        manager=self,
                        working_state_block=working_state_block,
                    )
                    if recovered:
                        continue
                raise

    def _chat_call_budget(self, settings: AppSettings, messages: list[ChatMessage]) -> dict[str, Any]:
        """Deadline for one non-streaming completion, scaled like the stream budgets."""
        prompt_tokens = estimate_prompt_tokens(messages)
        return {
            "call_deadline_ms": compute_chat_call_deadline_ms(
                settings.inference,
                prompt_tokens=prompt_tokens,
                prompt_tps=self.state.prompt_tps,
            ),
            "stream_lane": "worker",
            "prompt_token_estimate": prompt_tokens,
        }

    def _chat_stream_deadlines(self, settings: AppSettings, messages: list[ChatMessage]) -> dict[str, Any]:
        prompt_tokens = estimate_prompt_tokens(messages)
        first_ms, idle_ms = compute_chat_stream_deadlines(
            settings.inference,
            prompt_tokens=prompt_tokens,
            prompt_tps=self.state.prompt_tps,
        )
        return {
            "first_token_deadline_ms": first_ms,
            "idle_deadline_ms": idle_ms,
            "stream_lane": "worker",
            "prompt_token_estimate": prompt_tokens,
        }

    async def chat_stream(
        self,
        messages: list[Any],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = False,
        extra: dict[str, Any] | None = None,
        settings: AppSettings | None = None,
        working_state_block: str | None = None,
    ) -> AsyncIterator[str]:
        if not self.provider:
            raise RuntimeError("Inference model is not loaded")
        async with self._request_lease.shared():
            async for delta in self._chat_stream_holding_lease(
                messages,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                max_tokens=max_tokens,
                thinking=thinking,
                extra=extra,
                settings=settings,
                working_state_block=working_state_block,
            ):
                yield delta

    async def _chat_stream_holding_lease(
        self,
        messages: list[Any],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = False,
        extra: dict[str, Any] | None = None,
        settings: AppSettings | None = None,
        working_state_block: str | None = None,
    ) -> AsyncIterator[str]:
        app_settings = settings or load_settings()
        profile = self._active_profile(app_settings)
        typed = [
            message if isinstance(message, ChatMessage) else ChatMessage(role="user", content=str(message))
            for message in messages
        ]
        typed = sanitize_messages_for_inference(typed)
        overflow_retries = 0
        while True:
            fitted_tools: list[dict[str, Any]] | None = None
            preflight = await prepare_inference(
                typed,
                fitted_tools,
                profile,
                max_tokens,
                app_settings,
                manager=self,
                working_state_block=working_state_block,
            )
            typed = preflight.messages
            prepared = self.prepare_chat_messages(typed, max_tokens=max_tokens)
            extra_payload = self._with_n_keep(extra, prepared, max_tokens)
            try:
                async for delta in self.provider.chat_stream(
                    prepared,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    max_tokens=max_tokens,
                    thinking=thinking,
                    extra=extra_payload,
                    **self._chat_stream_deadlines(app_settings, prepared),
                ):
                    yield delta
                return
            except APIStatusError as exc:
                if is_n_keep_overflow(getattr(exc, "body", None)) or is_n_keep_overflow(exc):
                    if not self._adopt_n_keep_overflow(exc):
                        raise
                    prepared = self.prepare_chat_messages(typed, max_tokens=max_tokens)
                    extra_payload = self._with_n_keep(extra, prepared, max_tokens)
                    n_ctx = self.live_context_size()
                    keep = int(extra_payload.get("n_keep") or 0)
                    if n_ctx > 0 and keep >= n_ctx:
                        raise RuntimeError(n_keep_overflow_message(keep, n_ctx)) from exc
                    async for delta in self.provider.chat_stream(
                        prepared,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        max_tokens=max_tokens,
                        thinking=thinking,
                        extra=extra_payload,
                        **self._chat_stream_deadlines(app_settings, prepared),
                    ):
                        yield delta
                    return
                if is_context_overflow(exc) and overflow_retries < 1:
                    overflow_retries += 1
                    typed, fitted_tools, recovered = await recover_context_after_overflow(
                        typed,
                        fitted_tools,
                        profile,
                        max_tokens,
                        app_settings,
                        manager=self,
                        working_state_block=working_state_block,
                    )
                    if recovered:
                        continue
                raise

    def _vision_requested(self, settings: AppSettings, vision: bool | None) -> bool:
        return resolve_vision(settings, vision)

    async def load(
        self,
        settings: AppSettings,
        profile_name: str | None = None,
        context_size: int | None = None,
        force: bool = False,
        vision: bool | None = None,
        gguf_path: str | None = None,
    ) -> InferenceState:
        async with self._lock:
            profile = self._active_profile(
                settings,
                profile_name,
                gguf_path=gguf_path,
                context_size=context_size,
            )
            backend = resolve_backend(settings)
            model = profile_gguf(profile)
            same = (
                not force
                and self.backend
                and self.state.loaded
                and self.state.profile == profile.name
                and self.state.model_path == str(model)
                and self.backend.name == backend.name
                and int(self.state.context_size or 0) >= int(profile.context_size or 0)
                and (not vision or self.state.vision_loaded)
            )
            if same:
                return self.state
            return await self._load_locked(
                settings,
                profile.name,
                context_size=context_size or profile.context_size,
                vision=vision,
                gguf_path=gguf_path if gguf_path is not None else (profile.absolute_path or None),
            )

    async def ensure_runtime(
        self,
        settings: AppSettings,
        profile_name: str | None = None,
        *,
        context_size: int | None = None,
        vision: bool = False,
    ) -> InferenceState:
        """Reload only when context must grow or vision must be attached."""
        async with self._lock:
            if not self.state.loaded or not self.provider:
                return await self._load_locked(
                    settings,
                    profile_name,
                    context_size=context_size,
                    vision=vision,
                )
            want_context = int(context_size or self.state.context_size or 0)
            want_vision = bool(vision)
            if (
                (self.state.context_size or 0) >= want_context
                and (not want_vision or self.state.vision_loaded)
            ):
                return self.state
            return await self._load_locked(
                settings,
                profile_name or self.state.profile,
                context_size=want_context,
                vision=want_vision,
                force=True,
            )

    async def ensure_vision(self, settings: AppSettings) -> InferenceState:
        """Attach mmproj for an in-flight vision request. Does not keep it at idle."""
        if self.state.vision_loaded:
            return self.state
        manages = bool(self.backend and getattr(self.backend, "manages_process", False))
        if not manages:
            profile = self._active_profile(settings)
            projector = resolve_mmproj(profile)
            self.state.vision_loaded = True
            self.state.vision = True
            if projector is not None:
                self.state.mmproj_path = str(projector)
            return self.state
        return await self.ensure_runtime(
            settings,
            self.state.profile,
            context_size=self.state.context_size,
            vision=True,
        )

    async def release_vision(self, settings: AppSettings) -> InferenceState:
        """Detach mmproj after a vision request finishes.

        vision_mode "always" keeps the projector loaded. Lazy/off unload it so
        the LLM no longer shares VRAM with mmproj.
        """
        mode = str(getattr(settings.inference, "vision_mode", None) or "lazy").strip().lower()
        flag = settings.inference.vision
        if isinstance(flag, str) and flag.strip():
            mode = flag.strip().lower()
        if mode in {"always", "on", "enabled"}:
            return self.state
        if not self.state.vision_loaded:
            return self.state
        manages = bool(self.backend and getattr(self.backend, "manages_process", False))
        if not manages:
            self.state.vision_loaded = False
            self.state.vision = False
            self.state.mmproj_path = ""
            return self.state
        async with self._lock:
            return await self._load_locked(
                settings,
                self.state.profile,
                context_size=self.state.context_size,
                vision=False,
                force=True,
            )

    async def _load_locked(
        self,
        settings: AppSettings,
        profile_name: str | None,
        *,
        context_size: int | None,
        vision: bool | None,
        force: bool = False,
        gguf_path: str | None = None,
    ) -> InferenceState:
        profile = self._active_profile(
            settings,
            profile_name,
            gguf_path=gguf_path,
            context_size=context_size,
        )
        backend = resolve_backend(settings)
        model = profile_gguf(profile)
        want_vision = self._vision_requested(settings, vision)
        want_context = int(
            context_size
            or _default_load_context(profile)
            or profile.context_size
        )

        missing: list[str] = []
        if backend.requires_local_files:
            missing = backend.missing_requirements(profile)
        if missing:
            self.state.last_error = "; ".join(missing)
            raise FileNotFoundError(self.state.last_error)

        reusable = (
            not force
            and self.backend
            and self.state.loaded
            and self.state.profile == profile.name
            and self.state.model_path == str(model)
            and self.backend.name == backend.name
            and (self.state.context_size or 0) >= want_context
            and (not want_vision or self.state.vision_loaded)
        )
        if reusable:
            return self.state

        self._apply_profile_state(settings, profile, backend, model, want_context, want_vision)

        probe_timeout = 8.0 if not backend.manages_process else 6.0
        probe = await probe_remote_server(
            settings.inference.host,
            settings.inference.port,
            settings.inference.api_key,
            timeout=probe_timeout,
        )
        already_running = (self.backend is None or self.backend.pid is None) and bool(probe.get("ok"))
        if already_running and not backend.manages_process:
            advertised = list(probe.get("models") or [])
            self._record_probe(probe, settings)
            self.backend = backend
            self.backend.last_probe = probe
            self.provider = self._make_provider(settings, advertised)
            self.state.loaded = True
            self.state.loading = False
            self.state.pid = backend.pid
            await self.refresh_resources()
            self._invalidate_status_cache()
            return self.state

        if self.backend:
            await self.backend.stop()
        self.backend = backend
        self.state.loading = True
        self.state.last_error = ""
        started = time.time()

        start_timeout = 8.0 if not backend.manages_process else 300.0
        start_kwargs: dict[str, Any] = {
            "timeout": start_timeout,
            "context_size": want_context,
            "vision": want_vision,
        }
        try:
            ready = await backend.start(profile, **start_kwargs)
        except TypeError:
            ready = await backend.start(profile, timeout=start_timeout)
        if not ready and backend.manages_process and want_context > 16384:
            fallback_ctx = 16384
            try:
                ready = await backend.start(
                    _with_context(profile, fallback_ctx),
                    timeout=240,
                    context_size=fallback_ctx,
                    vision=want_vision,
                )
            except TypeError:
                ready = await backend.start(_with_context(profile, fallback_ctx), timeout=240)
            if ready:
                self.state.context_size = fallback_ctx
        self.state.pid = backend.pid
        if not ready:
            self.state.loading = False
            self.state.last_error = f"{backend.name} did not become ready"
            detail = (
                f". See {logs_dir() / 'llama-server.log'}"
                if backend.manages_process
                else f" at {self.base_url(settings)}"
            )
            raise RuntimeError(self.state.last_error + detail)

        advertised = list((backend.last_probe or {}).get("models") or [])
        if backend.last_probe:
            self._record_probe(backend.last_probe, settings)
        self.state.loaded = True
        self.state.loading = False
        self.state.load_time_seconds = round(time.time() - started, 2)
        self.provider = self._make_provider(settings, advertised)
        await self.refresh_resources()
        self._invalidate_status_cache()
        return self.state

    def _apply_profile_state(
        self,
        settings: AppSettings,
        profile: ModelProfile,
        backend: InferenceBackend,
        model: Path,
        context_size: int,
        vision: bool,
    ) -> None:
        self.state.profile = profile.name
        self.state.quant = profile.quant
        self.state.model_path = str(model) if backend.requires_local_files else ""
        self.state.gguf_path = str(profile.absolute_path or "") if backend.requires_local_files else ""
        projector = resolve_mmproj(profile) if vision else None
        self.state.vision_loaded = bool(vision and projector is not None)
        self.state.mmproj_path = str(projector) if self.state.vision_loaded else ""
        self.state.vision_mode = settings.inference.vision_mode or "lazy"
        self.state.vision = bool(vision)
        self.state.host = settings.inference.host
        self.state.port = settings.inference.port
        self.state.context_size = int(context_size or profile.context_size)
        self.state.backend = backend.name
        self.state.manages_process = backend.manages_process
        self.state.family = profile.family
        self.state.alias = profile.alias
        self.state.thinking_mode = profile.thinking_mode
        self.state.remote_model = settings.inference.remote_model

    def _record_probe(self, probe: dict[str, Any], settings: AppSettings) -> None:
        self.state.advertised_models = list(probe.get("models") or [])
        self.state.health_path = str(probe.get("health_path") or "")
        self.state.remote_model = self.provider_model(settings, self.state.advertised_models)
        live = int(probe.get("n_ctx") or probe.get("context_size") or 0)
        if live > 0:
            self.adopt_server_n_ctx(live)

    async def unload(self) -> InferenceState:
        async with self._lock:
            if self.backend:
                await self.backend.stop()
            self.provider = None
            self.state.loaded = False
            self.state.loading = False
            self.state.pid = None
            self.state.vision_loaded = False
            self.state.mmproj_path = ""
            self._invalidate_status_cache()
            return self.state

    @staticmethod
    def _invalidate_status_cache() -> None:
        try:
            from .status_monitor import STATUS_MONITOR

            STATUS_MONITOR.invalidate()
        except Exception:
            pass

    def mark_unloaded(self, error: str = "") -> None:
        """Reflect that the live instance is gone. Does not talk to the server."""
        self.provider = None
        self.state.loaded = False
        self.state.loading = False
        self.state.last_error = error
        self.state.server_n_ctx = 0
        self._invalidate_status_cache()

    async def apply_context(
        self,
        settings: AppSettings,
        context_size: int,
        *,
        allow_shrink: bool = False,
        allow_reload: bool = False,
    ) -> int:
        """Set the live context window. Mid-task callers pass allow_shrink=False so we only grow.

        Local LM Studio may reload an idle instance only when ``allow_reload`` is true
        (turn start). Mid-turn callers compact or trim; they never unload that server.
        Other external servers stay capped at their actual loaded slot.

        A Jarvis-owned llama.cpp process is different: the slot it booted with is
        not a ceiling. Growing past ``server_n_ctx`` reloads that process at the
        requested window, up to the hardware cap the caller already chose.
        """
        target = int(context_size or 0)
        if target <= 0:
            return int(self.state.context_size or 0)
        live_cap = int(self.state.server_n_ctx or 0)
        manages = bool(self.backend and getattr(self.backend, "manages_process", False))
        if allow_reload and target > live_cap and self.state.backend in LMSTUDIO_ALIASES:
            from .lmstudio_context import LocalContextRestoreError, grow_local_instance
            identifier = getattr(self.provider, "model", "")
            try:
                grown = await grow_local_instance(
                    settings,
                    target,
                    identifier,
                    lease=self._request_lease,
                    on_unloaded=self.mark_unloaded,
                )
            except LocalContextRestoreError as exc:
                if self.state.loaded:
                    self.mark_unloaded(str(exc))
                raise
            if grown:
                self.state.server_n_ctx = grown
                self.state.context_size = grown
                live_cap = grown
        # External servers cannot grow past the slot they already loaded.
        # Managed llama.cpp can, so do not clamp before the reload below.
        if live_cap > 0 and not manages:
            target = min(target, live_cap)
        current = int(self.state.context_size or 0)
        if live_cap > 0 and current > live_cap and not manages:
            self.state.context_size = live_cap
            current = live_cap
        if current == target:
            return current
        if not allow_shrink and current >= target and current > 0:
            return current
        if not manages:
            self.state.context_size = target
            return target
        try:
            await self.load(
                settings,
                self.state.profile or settings.inference.profile,
                context_size=target,
                force=True,
            )
        except Exception:
            return int(self.state.context_size or current)
        return int(self.state.context_size or target)

    @staticmethod
    def _probe_nvidia_smi_memory() -> str:
        """Sync nvidia-smi probe — always run via asyncio.to_thread from the event loop."""
        import subprocess

        return subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()

    async def refresh_resources(self) -> None:
        try:
            # Never block the FastAPI event loop on a hung/slow nvidia-smi (5s timeout).
            out = await asyncio.to_thread(self._probe_nvidia_smi_memory)
            if out:
                self.state.vram_used_mib = int(float(out.splitlines()[0].strip()))
        except Exception:
            pass
        try:
            if self.state.pid:
                ram_gb = await asyncio.to_thread(
                    lambda: round(psutil.Process(self.state.pid).memory_info().rss / (1024**3), 2)
                )
                self.state.ram_used_gb = ram_gb
        except Exception:
            pass

    @staticmethod
    def _ram_policy_snapshot(settings: AppSettings, profile: Any) -> dict[str, Any]:
        from .ram_policy import hardware_context_ceiling, offload_summary

        offload = offload_summary(settings)
        effective = hardware_context_ceiling(profile, settings)
        return {
            "context_effective_cap": effective,
            "ram_offload": offload,
        }

    def live_state_overlay(self) -> dict[str, Any]:
        """Cheap in-memory fields for status-cache readers (no GPU/HTTP probes)."""
        settings = load_settings()
        profile = self._active_profile(settings)
        active_model = None
        if self.state.loaded:
            active_model = (
                self.provider.model
                if self.provider
                else self.provider_model(settings, self.state.advertised_models)
            )
        return {
            "loaded": self.state.loaded,
            "loading": self.state.loading,
            "last_error": self.state.last_error,
            "profile": self.state.profile or profile.name,
            "pid": self.state.pid,
            "model_path": self.state.model_path,
            "mmproj_path": self.state.mmproj_path,
            "vision_loaded": self.state.vision_loaded,
            "context_size": self.state.context_size if self.state.loaded else _default_load_context(profile),
            "server_n_ctx": self.state.server_n_ctx,
            "load_time_seconds": self.state.load_time_seconds,
            "tokens_per_second": self.state.generation_tps,
            "prompt_tokens_per_second": self.state.prompt_tps,
            "advertised_models": self.state.advertised_models or [],
            "health_path": self.state.health_path,
            "remote_model": self.state.remote_model or settings.inference.remote_model,
            "inference_backend": self.state.backend,
            "manages_process": self.state.manages_process,
            "family": (self.state.family or profile.family) if self.state.loaded else profile.family,
            "thinking_mode": (
                self.state.thinking_mode or profile.thinking_mode or ("selective" if profile.thinking else "off")
            ),
            "quantization": self.state.quant or profile.quant,
            "active_model": active_model,
        }

    def unprobed_snapshot(self, settings: AppSettings) -> dict[str, Any]:
        """Fail-closed status payload when no successful probe has ever completed."""
        return self._assemble_snapshot(settings, healthy=False)

    def _assemble_snapshot(self, settings: AppSettings, *, healthy: bool) -> dict[str, Any]:
        profile = self._active_profile(settings)
        context_target = min(
            int(settings.inference.context_size or 32768),
            int(profile.context_size or 32768),
        )
        live_slot = int(self.state.server_n_ctx or 0)
        context_warning = ""
        if self.state.loaded and not self.state.manages_process and live_slot and live_slot < context_target:
            context_warning = (
                f"The external model server is loaded at {live_slot:,} tokens. "
                f"Reload that model with at least {context_target:,} context tokens; "
                "Jarvis cannot enlarge an already running server slot."
            )
        return {
            "loaded": self.state.loaded,
            "loading": self.state.loading,
            "healthy": bool(healthy),
            "active_model": (
                (self.provider.model if self.provider else self.provider_model(settings, self.state.advertised_models))
                if self.state.loaded
                else None
            ),
            "official_model": profile.repo,
            "family": (self.state.family or profile.family) if self.state.loaded else profile.family,
            "thinking_mode": (
                self.state.thinking_mode or profile.thinking_mode or ("selective" if profile.thinking else "off")
            ),
            "vision": settings.inference.vision,
            "quantization": self.state.quant or profile.quant,
            "profile": self.state.profile or profile.name,
            "context_size": self.state.context_size if self.state.loaded else _default_load_context(profile),
            "server_n_ctx": self.state.server_n_ctx,
            "context_target": context_target,
            "context_warning": context_warning,
            "quick_reply_output_limit": settings.front_responder.max_output_tokens,
            "context_cap": profile.context_size,
            "inference_backend": self.state.backend,
            "manages_process": self.state.manages_process,
            "gpu_layers": "auto (--fit on)" if settings.inference.fit else "99",
            **self._ram_policy_snapshot(settings, profile),
            "flash_attn": settings.inference.flash_attn,
            "host": settings.inference.host,
            "port": settings.inference.port,
            "base_url": self.base_url(settings),
            "advertised_models": self.state.advertised_models or [],
            "health_path": self.state.health_path,
            "remote_model": self.state.remote_model or settings.inference.remote_model,
            "api_key_configured": bool((settings.inference.api_key or "").strip()),
            "vram_used_mib": self.state.vram_used_mib,
            "ram_used_gb": self.state.ram_used_gb,
            "tokens_per_second": self.state.generation_tps,
            "prompt_tokens_per_second": self.state.prompt_tps,
            "load_time_seconds": self.state.load_time_seconds,
            "pid": self.state.pid,
            "last_error": self.state.last_error,
            "model_path": self.state.model_path,
            "mmproj_path": self.state.mmproj_path,
            "vision_loaded": self.state.vision_loaded,
            "thinking": profile.thinking,
            "vision_mode": settings.inference.vision_mode or "lazy",
            "profiles": [
                {
                    "name": p.name,
                    "label": p.label,
                    "family": p.family,
                    "thinking_mode": p.thinking_mode,
                    "context_size": p.context_size,
                }
                for p in _snapshot_profiles()
            ],
            "context_policy": {
                "live": self.live_context_size() or profile.context_size,
                "profile_cap": profile.context_size,
                "effective_cap": self._ram_policy_snapshot(settings, profile)["context_effective_cap"],
                "server_n_ctx": self.state.server_n_ctx,
                "note": "Tasks start at 8K or 16K and expand toward the RAM-aware cap when the live prompt is under pressure.",
            },
        }

    async def live_snapshot(self, settings: AppSettings) -> dict[str, Any]:
        """Full probe path: GPU/process resources + provider health. Used by the monitor."""
        await self.refresh_resources()
        healthy = False
        if self.provider:
            healthy = await self.provider.health()
        return self._assemble_snapshot(settings, healthy=healthy)

    async def snapshot(self, settings: AppSettings, *, live: bool = False) -> dict[str, Any]:
        """Status readers prefer the cached monitor snapshot unless ``live=True``.

        Only the process-wide ``MANAGER`` singleton participates in the shared
        status cache. Ad-hoc ``InferenceManager()`` instances always probe live
        so unit tests and one-off managers cannot read another instance's state.
        """
        if live or self is not MANAGER:
            return await self.live_snapshot(settings)
        from .status_monitor import STATUS_MONITOR

        return await STATUS_MONITOR.get_snapshot(settings)

    async def record_timings(self, timings: dict[str, Any]) -> None:
        if not timings:
            return
        predicted = timings.get("predicted_per_second") or timings.get("predicted_n")
        prompt = timings.get("prompt_per_second")
        if isinstance(predicted, (int, float)):
            self.state.generation_tps = round(float(predicted), 2)
        if isinstance(prompt, (int, float)):
            self.state.prompt_tps = round(float(prompt), 2)
        try:
            from .benchmarks import record_benchmark_sample

            await record_benchmark_sample(
                profile=self.state.profile,
                quantization=self.state.quant,
                context_size=self.state.context_size,
                prompt_tps=self.state.prompt_tps,
                generation_tps=self.state.generation_tps,
                vram_used_mib=self.state.vram_used_mib,
                ram_used_gb=self.state.ram_used_gb,
                load_time_seconds=self.state.load_time_seconds,
                source="timing",
            )
        except Exception:
            pass


def _snapshot_profiles() -> list[ModelProfile]:
    profiles = list(declared_profiles())
    extra = qwen38_9b_profile()
    if extra is not None and extra.name not in {item.name for item in profiles}:
        profiles.insert(0, extra)
    return profiles


MANAGER = InferenceManager()
