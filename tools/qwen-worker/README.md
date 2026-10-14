# Local Qwen coding worker

Qwen Code provides file-reading, file-editing and shell tools around a local Ollama model. Cursor can delegate a specific implementation task through its terminal, then inspect the resulting diff and checks. This does not change Cursor's supervising model or subscription usage.

## One-time local setup

Use an existing Ollama installation listening on `127.0.0.1:11434`. Qwen Code 0.25.0 was validated on Windows PowerShell 5.1 with Node.js and the official `qwen3.5:4b` model. These optional setup commands download the harness and model weights; they do not make paid inference calls:

```powershell
npm.cmd install -g @qwen-code/qwen-code@0.25.0
ollama pull qwen3.5:4b
ollama create anzu-qwen-worker:latest -f .\tools\qwen-worker\QwenWorker.Modelfile
ollama launch qwen --model anzu-qwen-worker:latest --config
```

The Modelfile sets a 32768-token context and a 4096-token response limit. Size context and model choice for available memory. This 4B worker was selected because the test machine's 16GB GPU was shared with existing inference services.

In the `anzu-qwen-worker:latest` provider entry under `modelProviders.openai` in the generated Qwen settings, use:

```json
"generationConfig": {
  "contextWindowSize": 32768,
  "timeout": 300000,
  "extra_body": { "reasoning_effort": "none", "keep_alive": -1 },
  "samplingParams": { "temperature": 0.6, "max_tokens": 4096 }
}
```

Keep the provider base URL at `http://127.0.0.1:11434/v1`. Ollama ignores the local SDK placeholder key; no cloud credential is needed. The invocation script never installs a harness, pulls models, modifies server settings, or starts a cloud fallback.

## Delegate code changes

```powershell
powershell.exe -NoProfile -File .\tools\qwen-worker\Invoke-QwenWorker.ps1 -Task "Implement the named ticket's specific subtask and run relevant tests."
```

The default repository is the checkout containing this script. Use `-Repo` to select another checkout or worktree. For long prompts use `-TaskFile` with a UTF-8 file. `-MaxTurns` defaults to 30 and `-TimeLimit` to `20m`.

This headless worker can actually edit the selected checkout and execute shell commands. File edits and the shell tool are pre-approved for the delegated development task. It is not an OS sandbox. Give it a concrete scope; review its changes and verify its test results. Commits, pushes, merges and deployments require explicit inclusion in the task.

The launcher requires local weights, forces OpenAI-compatible authentication against numeric loopback, and returns Qwen Code's exit status. The Cursor rule supplies the invocation to agents with terminal access. A persistent daemon is not required for this subprocess-based delegation.

## Validation

The configured worker created JavaScript implementation/test files through its tools and ran the test. The result was independently rerun successfully. This proves the basic file-edit/test loop, not acceptance of arbitrary ANZU changes.

References: [Qwen headless mode](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/), [Ollama model](https://ollama.com/library/qwen3.5:4b).
