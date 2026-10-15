# ANZU computer, browser, and internet capabilities

RFC-0217 extends the existing desktop, Playwright and HTTP tools with an owner-shared Chrome connector, web search and isolated optional workers.

| Capability | Available implementation |
| --- | --- |
| Windows apps | Desktop UI Automation, screenshots and Reflex; Windows interactive desktop required |
| Separate browser | Playwright persistent profile, page controls, screenshots, uploads/downloads |
| Internet | HTTP fetch and built-in browser search through DuckDuckGo, Google or Bing |
| Existing Chrome tab | Shared-tab snapshots, text search, click/fill, permitted frames and open shadow roots |
| Chrome files | Observed-link downloads and owner-authorized uploads up to 20 MiB |
| Ad blocking | Tab-scoped request rules compiled from 47,731 EasyList domains |
| Optional goal workers | Browser Use, Microsoft UFO and Cua Driver in separate Python environments |

## Chrome setup

On Tools, choose **Prepare** in the Chrome connector card. This copies the extension to `%LOCALAPPDATA%\ANZU\chrome-extension` and registers the native host for the current Windows user. The stable extension ID is `infekcmclohfmmclkhcjmnolcgiokege`.

1. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select that prepared folder.
2. Open your website, click the ANZU extension and **Share this tab**. Grant the requested site access. The ON badge shows sharing.
3. To include embedded websites, select the popup checkbox and grant their site access when Chrome asks.
4. Ask ANZU to inspect or act on the shared website. After navigation, share the destination again.

A ZIP is also available from Tools. Extract it to a permanent folder and load its `chrome` folder. Run `install-host.ps1` there to register the bundled native executable; the script derives the extension ID automatically. A real Python interpreter is a fallback when the native executable is absent. No administrator rights or ANZU API token is needed.

## Tool examples

```json
{"action":"search","text":"ANZU browser connector","provider":"duckduckgo"}
{"action":"chrome_status"}
{"action":"chrome_snapshot","url":"https://example.com/"}
{"action":"chrome_frames","url":"https://example.com/"}
{"action":"chrome_find","url":"https://example.com/","text":"shipping"}
{"action":"chrome_click","url":"https://example.com/","target_id":"ID_FROM_SNAPSHOT"}
{"action":"chrome_fill","url":"https://example.com/","target_id":"ID_FROM_SNAPSHOT","text":"hello"}
{"action":"chrome_block_ads","url":"https://example.com/","enabled":true}
```

Frame operations accept the observed `frame_id` and exact `frame_url`. Upload uses `chrome_upload`, an observed file-input `target_id` and an authorized local `path`; downloads use `chrome_download`, an observed link target and its exact `download_url`. Take another snapshot after mutations. Timeout responses require inspection before retrying a dispatched action. Downloads report completed, interrupted or still in progress honestly.

## Optional workers

Tools exposes Install now for Browser Use, UFO and Cua. Each installer uses `%LOCALAPPDATA%\ANZU\workers\<worker>\venv`, verifies its imports and records readiness only after success. These installs do not modify ANZU's Python environment. A real Python 3.11+ interpreter is required; packaged ANZU can use `JARVIS_WORKER_PYTHON`.

Browser Use uses its actual Python SDK and a separate browser profile restricted to the starting site. Cua uses the actual Cua Driver SDK with bounded UI tool calls. UFO uses Microsoft's checkout and CLI. Configure ANZU's local OpenAI-compatible model endpoint; workers inherit that explicit configuration. Worker success reports require independent inspection of the result.

## Scope and limits

- One explicitly shared HTTP(S) tab and exact URL. Navigation, closure, host disconnection or stopping sharing revokes access and clears tab rules.
- Visible page evidence and observed controls only. Passwords, hidden fields, cookies and arbitrary model-supplied scripts are excluded. Closed shadow roots and inaccessible frames remain unavailable.
- Cross-origin frames need both explicit embedded-site sharing and Chrome site permission. Cross-site navigation requires sharing the destination.
- EasyList compilation preserves domain and third-party scope. It omits 627 unsupported expressions and does not implement cosmetic filters or scriptlets. Blocking applies to future requests in the shared tab and does not guarantee removal of every ad. The packaged list includes source revision, digest and CC BY-SA attribution; updates are a build-time script, not a runtime subscription.
- Local native messaging has no HTTP listener. Other programs running as the same Windows user share the local trust boundary.
- Chrome site permissions persist until removed in Details → Site access; ANZU control still requires sharing. To remove, stop sharing, run `install-host.ps1 -Uninstall`, then remove the extension.

References: [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), [Chrome request rules](https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest), [Browser Use SDK](https://docs.browser-use.com/open-source/quickstart), [Cua Driver SDK](https://cua.ai/docs/cua-driver/guides/use-the-sdk), [Microsoft UFO](https://github.com/microsoft/UFO).

## Validation

Expanded focused tests: 96 Python checks and five Node checks passed. Real Chromium checks covered shadow roots, frames, chunked uploads, all compiled ad rules and request block/unblock. A separate Windows integration test passed with the compiled registered native host and loaded extension. Frontend build and lint passed. Expanded-head CI passed: 3,170 backend tests, six skips, frontend build and installer compile.

All three optional environments were installed on the development PC. Cua's native app inventory probe and UFO's CLI probe passed. Browser Use executed against the local Qwen model and visited the requested page, but returned an unreliable page-title answer; model quality is not signed off. Full local Windows pytest stalled at 14% while creating an asyncio Proactor loop in socketpair/accept; it was stopped and is not a local full-suite pass.

The prepared extension/native host can be tested in an isolated Chrome profile. Loading the extension in the owner's normal Chrome profile remains an activation step. Source-based installed ANZU requires a restart after updating its backend.
