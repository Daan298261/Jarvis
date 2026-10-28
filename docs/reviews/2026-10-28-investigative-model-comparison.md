# Local models for investigative analysis (2026-10-28)

No model card establishes a universal zero-refusal model. Reduced refusal behavior also does not establish factual accuracy, current knowledge or suitability as evidence.

## What was wrong locally

The installed API reported `0bserverx/qwen3.8-27b-heretic-abliterated-uncensored-gguf/rvn-q3_k_s-multilingual.gguf` while the screenshot's shortcut claimed Qwen3.8 9B. The catalog also matched that 9B candidate to a Qwen3.5 Defiant artifact and a Nemotron 4B candidate to Gemma E4B, using generic words as identity. `Path.stem` truncated dotted model identifiers to `Qwen3`, allowing unrelated sizes to resolve; a single advertised model also replaced any explicit request.

RFC-0242 requires family identity, removes those resolution fallbacks, disables absent models and separates shortcut registration from activation. None of this modifies security gates or system prompts.

## Candidates

| Model | Evidence for reduced refusals | Local artifact / size | Practical limitation |
| --- | --- | --- | --- |
| [Qwen3.8 9B Distill Heretic](https://huggingface.co/petruhonk/Qwen3.8-9B-Distill-uncensored-heretic) | Publisher reports **6 refusals out of 100** in its evaluation, compared with 98/100 for another ablation. This is publisher evidence, not an ANZU measurement. | [GGUF repository](https://huggingface.co/petruhonk/Qwen3.8-9B-Distill-uncensored-heretic-GGUF); existing Q6 candidate estimates 7.7 GiB of weights. The intended model is not installed on this PC. | Closest candidate to the intended selection; requires artifact verification, actual load, Dutch-language, factuality and tool tests before promotion. |
| [Dolphin 2.9.3 Mistral Nemo 12B](https://huggingface.co/dphn/dolphin-2.9.3-mistral-nemo-12b) | Publisher states its training data was filtered to remove alignment/bias and describes high compliance; the card does not establish a zero-refusal result. | [Publisher GGUFs](https://huggingface.co/dphn/dolphin-2.9.3-mistral-nemo-12b-gguf/tree/3060031394eb8ea97c82a219ec26c574c99298fe): Q4_K_M is **7,477,218,752 bytes (6.96 GiB)**. Added as an unbenchmarked catalog option. | Older model; no local quality/speed/refusal/tool certification. Training length was 8,192 tokens although its base supports a larger context. |
| [Huihui Qwen3.5 9B Abliterated](https://huggingface.co/huihui-ai/Huihui-Qwen3.5-9B-abliterated) | Publisher identifies the weights as abliterated. | A separate checkpoint from the installed DavidAU Defiant variant. | A useful comparison checkpoint; the name alone is not proof of better refusal behavior or tool reliability. |

All weight sizes exclude KV cache and runtime overhead. This PC reports an RTX 5070 Ti with approximately 15.9 GiB VRAM; simultaneous resident models and context length affect fit. Speed labels in the menu are provisional catalog estimates, not measured token rates.

Dolphin artifact verified from the publisher's Hugging Face API: revision `3060031394eb8ea97c82a219ec26c574c99298fe`, filename `dolphin-2.9.3-mistral-nemo-12b.Q4_K_M.gguf`, SHA-256 `654d033bd2ce70dc09e8a64067bc858cf15978598494142d67a48d35a4c4c521`, Apache-2.0. No new weights were downloaded or made the default.

## Validation limits

The currently serving 27B answered a direct, benign criminology question about why illicit-market price reports vary and why unsourced claims are unreliable. It returned analysis rather than refusing. That does **not** reproduce the original ammunition-price question or certify the replacement candidates. The original refusal may depend on the exact checkpoint, prompt and application context; the screenshot alone cannot identify which layer produced it.

For investigative evaluation, use a fixed, lawful casework corpus and score useful answers, source fidelity, unsupported claims, Dutch comprehension, refusal rate and tool behavior separately. Current illicit-market figures require dated, attributable sources; a more compliant model cannot supply missing evidence.
