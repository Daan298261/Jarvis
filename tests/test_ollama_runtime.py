"""Ollama runtime ensure (Umi brain)."""

from __future__ import annotations

import pytest

from app.inference import ollama_runtime
from app.persona.persona_brain import UMI_OLLAMA_MODEL, reflex_verify_brain_runtime


@pytest.mark.asyncio
async def test_ensure_local_ollama_already_up(monkeypatch):
    async def fake_probe(host, port, timeout=8.0, retry=False, api_key=""):
        return {"ok": True, "models": [UMI_OLLAMA_MODEL]}

    async def fake_gpu(**kwargs):
        return {"ok": True, "detail": "warm"}

    monkeypatch.setattr(ollama_runtime, "probe_remote_server", fake_probe)
    monkeypatch.setattr(ollama_runtime, "ensure_ollama_gpu", fake_gpu)

    result = await ollama_runtime.ensure_local_ollama(
        host="127.0.0.1",
        port=11434,
        model=UMI_OLLAMA_MODEL,
        pull_if_missing=False,
    )
    assert result["ok"] is True
    assert result["method"] == "ollama-ready"


def test_reflex_verify_brain_accepts_umi_runtime():
    assert reflex_verify_brain_runtime(persona_id="umi", runtime_name="umi-opus-9b") is True


def test_reflex_verify_brain_skips_unbound_persona():
    assert reflex_verify_brain_runtime(persona_id="anzu", runtime_name="umi-opus-9b") is True
