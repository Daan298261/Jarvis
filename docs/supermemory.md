# Supermemory sidecar

Jarvis can use the self-hosted [Supermemory](https://github.com/supermemoryai/supermemory) server for semantic recall. Jarvis ContextRepo remains authoritative and is always the fallback. Obsidian remains the owner-editable linked knowledge vault.

## Install on Windows

Open **Memory → Semantic memory module** and choose **Install locally**. Jarvis downloads the pinned official Windows binary, verifies its SHA-256, starts it with the active local OpenAI-compatible model endpoint, discovers the generated loopback API key from the Jarvis-owned data directory, and enables auto-start. Start, stop, enable, disable, health, and the local console remain available from the same card.

The local console URL is also exposed to Jarvis, so a computer-use task can open and operate the console when the owner asks. Installation and service lifecycle use the backend-native module manager rather than fragile screen automation.

For manual or recovery installation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap-supermemory.ps1
```

The bootstrap downloads the pinned `server-v0.0.8` Windows x64 asset from GitHub Releases and verifies its SHA-256. The binary and its runtime data are not committed to Git.

The upstream self-hosted Lite server is licensed for up to 10,000 documents. Jarvis does not bypass or alter that limit.

Start the server with an OpenAI-compatible LLM. This example uses a local LM Studio endpoint:

```powershell
$env:SUPERMEMORY_DATA_DIR = "$PWD\data\supermemory"
$env:OPENAI_BASE_URL = "http://127.0.0.1:1234/v1"
$env:OPENAI_API_KEY = "lm-studio"
$env:OPENAI_MODEL = "your-loaded-model-id"
$env:SUPERMEMORY_DISABLE_TELEMETRY = "1"
& .\runtime\supermemory\supermemory-server.exe
```

Keep the generated `sm_...` API key private. Jarvis discovers the key automatically for its managed loopback data directory without returning it from an API. For an externally managed or remote server, bind it through `POST /api/supermemory/credentials`, then enable the sidecar through `PUT /api/supermemory`:

```json
{"enabled": true, "base_url": "http://127.0.0.1:6767"}
```

Use `POST /api/supermemory/probe` to validate authenticated search and `POST /api/supermemory/sync/owner` to mirror existing native entries. Normal ContextRepo writes are mirrored automatically after the native transaction commits.

Remote endpoints are rejected unless `allow_remote` is explicitly enabled. A sidecar outage, timeout, malformed response, missing credential, or empty result falls back to native ContextRepo retrieval and never blocks a native memory write.
