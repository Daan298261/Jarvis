# ANZU computer, browser, and internet capabilities

RFC-0217 adds an optional connector to an existing Chrome session.

| Capability | Existing implementation | Requirement |
| --- | --- | --- |
| Windows applications | `desktop`: enumerate windows/controls, named click, typing, keys; screenshots and Reflex loop | Windows interactive desktop, pywinauto; model for goal-driven planning |
| Browser automation | `browser`: Playwright open/read/click/fill/press, screenshots, tabs, downloads/uploads | Playwright and Chromium; separate ANZU persistent profile |
| Internet and APIs | `web_fetch`: HTTP GET/HEAD/POST and downloads, redirect permissions | httpx; permitted internet/LAN scope |
| Web research | Open a search engine or named website with `browser`, inspect snapshot, follow results; use `web_fetch` for known URLs | No dedicated search-provider API key required; MCP can supply search providers |
| Optional goal workers | Browser Use, Microsoft UFO, Cua | Separate dependencies/configuration; availability is checked, never assumed |
| Existing signed-in Chrome tab | Connector actions on the `browser` tool | This extension, registered native host, explicitly shared tab |

The source inspection found working implementations for the first three capabilities. On the development PC, pywinauto, Playwright, httpx and pytest imports were present; Browser Use was absent. Import detection alone does not establish installed ANZU or end-to-end model readiness.

## Install the optional Chrome connector

1. Use the `chrome` folder in the provided ZIP, or `extensions/chrome` in the source checkout. Put it in a permanent location. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select that folder.
2. Copy the extension ID shown by Chrome. In PowerShell run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install-host.ps1 -ExtensionId YOUR_EXTENSION_ID -PythonExecutable C:\path\to\python.exe
   ```

   Run from the extension folder; use a real Python executable, not a Windows Store alias. Python 3.10+ is sufficient for the stdlib host. This registers only the current user's exact extension ID. No administrator rights or ANZU API key is needed.
3. Open the website you want ANZU to use. Click the extension and **Share this tab**, then grant Chrome's site-access request. Close the popup; the connector stays connected. The **ON** badge indicates sharing. Reopen it for status or **Stop sharing and disable ad blocking**.
4. Run ANZU from the branch containing RFC-0217. Ask it to use your shared Chrome tab. `browser(action="chrome_status")` reports the shared URL. This change does not update an already installed ANZU executable.

Example tool sequence:

```json
{"action":"chrome_snapshot","url":"https://example.com/"}
{"action":"chrome_find","url":"https://example.com/","text":"shipping"}
{"action":"chrome_click","url":"https://example.com/","target_id":"ID_FROM_SNAPSHOT"}
{"action":"chrome_block_ads","url":"https://example.com/","enabled":true}
```

Use `chrome_fill` with an observed `target_id` and `text`. After any mutation, take a new snapshot to verify the result. Clicks/fills use ANZU's existing consequential-action policy. Timeouts are ambiguous for dispatched mutations: inspect before retrying.

## Scope and limits

- One shared HTTP(S) tab; exact URL match. Navigation/reload, tab closure, host disconnection, browser restart, or stopping sharing revokes control and clears ad rules. Share again after navigation.
- No arbitrary page scripts, cookie access, password-field filling, file uploads, cross-origin link clicks, or control of other tabs. Snapshots use visible main-frame text and observed controls; page content is untrusted evidence. Iframes, shadow DOM, and CAPTCHA require another route or manual interaction.
- Basic ad blocking uses four common advertising domains and session rules limited to the shared tab. It prevents future matching requests; reload revokes sharing, so share again and re-enable afterward. It is not a full filter-list blocker or guaranteed removal of every ad.
- Chrome's content-blocking permission is declared at installation so advertising requests can be blocked without granting page-reading access to advertising domains. Website reading/interaction still needs the on-demand site permission and explicit tab sharing.
- The host communicates through Chrome native messaging and local files under `%LOCALAPPDATA%\ANZU\chrome-connector`. There is no HTTP listener. Other programs running as the same Windows user have the same local trust boundary.
- Chrome site permissions remain granted until you remove them through the extension's **Details → Site access** settings, but ANZU control always requires explicitly sharing a tab.

To remove: stop sharing, run `install-host.ps1 -ExtensionId YOUR_EXTENSION_ID -Uninstall`, then remove the extension in Chrome. Local host files may be deleted afterward.

Protocol references: [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), [declarativeNetRequest session rules](https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest).

## Validation on the development PC

99 focused Python checks and four Node checks passed. Real Chromium verified page operations, loaded extension/popup, and actual ad-request block/unblock. A real native-host process passed a stdio round trip. Live ANZU tool calls enumerated 18 visible Windows application windows and fetched a public HTTPS page. The full local pytest run stalled at 28% in async fixture setup; a process stack showed asyncio waiting and an idle aiosqlite worker. That run was stopped and is not a full-suite pass. The owner's normal Chrome installation and installed ANZU update remain unverified.
