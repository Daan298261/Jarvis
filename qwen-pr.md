Recover the abandoned local Qwen Code worker integration. The PowerShell harness invokes the real Ollama-backed coding agent against an explicitly supplied checkout, with actual file editing and test execution. Include its model recipe, usage guide, and opt-in Cursor delegation rule.

Recovered from cursor/qwen-local-worker-99ea; the worker is not launched by this merge. Validation: PowerShell AST parse and git diff --check passed. Existing live worker evidence remains separate from this branch integration; no installed runtime or model was changed.
