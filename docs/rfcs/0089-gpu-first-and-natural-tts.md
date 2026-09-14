# RFC-0089: GPU-first model load + natural TTS (no silent SAPI)

**Status:** accepted
**Queue item:** Voice quality / local inference GPU offload
**Author:** Taco via Cursor
**Date:** 2026-09-14

## Problem

LM Studio/Ollama often load on CPU. Switching voices still sounds robotic because Kokoro errors fall through to Windows SAPI, Chatterbox is env-gated, and Settings engine names do not match adapters. Trajectories repeat the same user prompt.

## Decision

GPU via `lms load --gpu max` / Ollama `num_gpu` / existing llama.cpp ngl—not computer-use. Neural TTS never silently becomes SAPI. Collapse duplicate trajectory prompts.

## Acceptance criteria

- [ ] LM Studio load path requests max GPU; Ollama chat sends `num_gpu` when NVIDIA is present
- [ ] Kokoro/Chatterbox failure does not return SAPI audio if a neural engine is installed
- [ ] `chatterbox_turbo` resolves to chatterbox, not system
- [ ] Trajectory inspect does not repeat the same user prompt as goal + summary + duplicate events
