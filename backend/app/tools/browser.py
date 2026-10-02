from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..config import AppSettings, live_workspace_roots_from_context, load_settings, playwright_user_data_dir
from ..mobile.wan_forward import lan_http_bind_for_url
from ..policy.network_http import _with_lan_bind
from .base import RiskLevel, Tool, ToolResult
from .owner_paths import chromium_download_launch_kwargs, owner_media_dir, resolve_owner_file_path
from .safety import resolve_allowed_path

_lock = asyncio.Lock()
_playwright = None
_browser = None
_context = None
_page = None
_pages: list[Any] = []

_ACTIONS_NEEDING_PAGE = {
    "open",
    "snapshot",
    "action_frame",
    "click",
    "type",
    "fill",
    "press",
    "evaluate",
    "screenshot",
    "tabs",
    "download",
    "upload",
    "title",
}

_NAMED_ROLES = ("button", "link", "tab", "menuitem", "checkbox", "radio")
_GOTO_RETRIES = 3
_INTERNAL_BROWSER_SCHEMES = ("about:", "chrome:", "devtools:", "data:")
_BLOCKED_BROWSER_SCHEMES = frozenset({"javascript", "vbscript", "blob", "ws", "wss"})
_allowed_override: list[str] | None = None


def file_url_to_path(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc.lower() not in {"", "localhost", "127.0.0.1"}:
        return f"//{parsed.netloc}{path}"
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        return path[1:]
    return path


def looks_like_workspace_file_target(raw: str) -> bool:
    text = str(raw or "").strip().strip('"')
    if not text:
        return False
    scheme = (urlparse(text).scheme or "").lower()
    if scheme == "file":
        return True
    if scheme in {"http", "https"} or scheme in _BLOCKED_BROWSER_SCHEMES or scheme == "data":
        return False
    return "/" in text or "\\" in text or text.startswith("~") or (len(text) >= 2 and text[1] == ":")


def resolve_browser_open_url(raw: str, allowed: list[str]) -> str:
    """http(s) URLs pass through; local workspace files become file:// URIs."""
    text = str(raw or "").strip()
    scheme = (urlparse(text).scheme or "").lower()
    if scheme in {"http", "https"}:
        return text
    if scheme in _BLOCKED_BROWSER_SCHEMES or scheme == "data":
        raise PermissionError("Blocked URL scheme. Only http, https, and workspace files are allowed")
    if scheme == "file" or looks_like_workspace_file_target(text):
        path_text = file_url_to_path(text) if scheme == "file" else text
        return Path(resolve_allowed_path(path_text, allowed)).as_uri()
    raise PermissionError("Blocked URL scheme. Only http, https, and workspace files are allowed")


def _browser_allowed() -> list[str]:
    if _allowed_override is not None:
        return live_workspace_roots_from_context({"allowed_directories": list(_allowed_override)})
    try:
        from .registry import REGISTRY

        live = getattr(REGISTRY, "_live_context", None)
        if callable(live):
            return live_workspace_roots_from_context(live())
        return live_workspace_roots_from_context(getattr(REGISTRY, "_context", {}) or {})
    except Exception:
        pass
    return live_workspace_roots_from_context()


def redirect_chain_urls(response: Any, final_url: str = "") -> list[str]:
    """Oldest-first hop URLs from a Playwright navigation response, plus the final page URL."""
    hops: list[str] = []
    req = getattr(response, "request", None) if response is not None else None
    while req is not None:
        url = str(getattr(req, "url", "") or "").strip()
        if url:
            hops.append(url)
        req = getattr(req, "redirected_from", None)
    hops.reverse()
    final = str(final_url or "").strip()
    if final and (not hops or hops[-1] != final):
        hops.append(final)
    return hops


def gate_browser_url(url: str, action: str = "open") -> str | None:
    """Return an error string when this hop is not allowed; None when it may proceed."""
    cleaned = (url or "").strip()
    if not cleaned or cleaned.lower().startswith(_INTERNAL_BROWSER_SCHEMES):
        return None
    scheme = (urlparse(cleaned).scheme or "").lower()
    if scheme == "file":
        try:
            resolve_allowed_path(file_url_to_path(cleaned), _browser_allowed())
        except PermissionError as exc:
            return str(exc)
        return None
    if scheme and scheme not in {"http", "https"}:
        return "Blocked URL scheme. Only http, https, and workspace files are allowed"
    from ..policy.computer_permissions import evaluate_tool_permissions

    gate = evaluate_tool_permissions("browser", {"url": cleaned, "action": action})
    if gate.status == "deny":
        return gate.reason
    if gate.status == "ask":
        return gate.reason or "Permission required before the browser can reach the network."
    return None


async def _blank_page(page) -> None:
    try:
        await page.goto("about:blank", wait_until="domcontentloaded", timeout=5_000)
    except Exception:
        pass


async def _abandon_disallowed_page(page, reason: str) -> None:
    await _blank_page(page)
    raise PermissionError(reason)


def _bind_event(target: Any, event: str, handler: Any) -> bool:
    adder = getattr(target, "on", None) if target is not None else None
    if not callable(adder):
        return False
    try:
        adder(event, handler)
        return True
    except Exception:
        return False


def _unbind_event(target: Any, event: str, handler: Any) -> None:
    if target is None:
        return
    for name in ("remove_listener", "off"):
        remover = getattr(target, name, None)
        if callable(remover):
            try:
                remover(event, handler)
                return
            except Exception:
                continue


def _context_pages(page) -> list[Any]:
    ctx = getattr(page, "context", None)
    pages = list(getattr(ctx, "pages", None) or [])
    ordered: list[Any] = []
    for item in [page, *pages]:
        if item is not None and item not in ordered:
            ordered.append(item)
    return ordered


async def _assert_navigation_allowed(page, response: Any, action: str) -> None:
    hops = redirect_chain_urls(response, str(getattr(page, "url", "") or ""))
    for hop in hops:
        blocked = gate_browser_url(hop, action)
        if blocked:
            await _abandon_disallowed_page(page, blocked)


async def _assert_current_url_allowed(page, action: str) -> None:
    blocked = gate_browser_url(str(getattr(page, "url", "") or ""), action)
    if blocked:
        await _abandon_disallowed_page(page, blocked)


def _set_active_page(page) -> None:
    global _page, _pages
    _page = page
    if page is not None and page not in _pages:
        _pages.append(page)


async def activate_browser_tab(pages: list[Any], index: int, action: str = "open") -> Any:
    """Switch to an existing tab after hop-gating its URL. Fail closed on a denied hop."""
    if index < 0 or index >= len(pages):
        raise IndexError(f"No tab at index {index}")
    chosen = pages[index]
    await _assert_current_url_allowed(chosen, action)
    _set_active_page(chosen)
    return chosen


async def _run_and_gate_navigation(page, coro, action: str = "open") -> Any:
    """Run an interaction, then re-gate every captured hop, spawned tab, and final URL."""
    hops: list[str] = []
    spawned: list[Any] = []

    def _on_response(response: Any) -> None:
        hops.extend(redirect_chain_urls(response, str(getattr(response, "url", "") or "")))

    def _on_page(new_page: Any) -> None:
        if new_page is not None and new_page not in spawned:
            spawned.append(new_page)
            _bind_event(new_page, "response", _on_response)

    ctx = getattr(page, "context", None)
    bound_page = _bind_event(page, "response", _on_response)
    bound_ctx_page = _bind_event(ctx, "page", _on_page)
    bound_ctx_response = _bind_event(ctx, "response", _on_response)
    result: Any = None
    try:
        result = await coro
        await _wait_stable(page)
        for extra in spawned:
            await _wait_stable(extra)
    finally:
        if bound_page:
            _unbind_event(page, "response", _on_response)
        if bound_ctx_page:
            _unbind_event(ctx, "page", _on_page)
        if bound_ctx_response:
            _unbind_event(ctx, "response", _on_response)
        for extra in spawned:
            _unbind_event(extra, "response", _on_response)
    pages = _context_pages(page)
    for extra in spawned:
        if extra not in pages:
            pages.append(extra)
    ordered: list[str] = []
    for hop in hops + [str(getattr(item, "url", "") or "") for item in pages]:
        if hop and hop not in ordered:
            ordered.append(hop)
    for hop in ordered:
        blocked = gate_browser_url(hop, action)
        if blocked:
            for item in pages:
                await _blank_page(item)
            raise PermissionError(blocked)
    if spawned:
        _set_active_page(spawned[-1])
    return result


def browser_permission_url(action: str, kwargs: dict[str, Any] | None, current_url: str = "") -> str:
    """Use the open URL for follow-on actions so LAN pages stay network.local."""
    supplied = str((kwargs or {}).get("url") or "").strip()
    if supplied:
        return supplied
    if action != "open":
        return str(current_url or "").strip()
    return ""


def _browser_error(exc: BaseException) -> str:
    if isinstance(exc, ModuleNotFoundError):
        return "Playwright is not installed on this PC, so I cannot open a browser."
    text = str(exc)
    lowered = text.lower()
    if "executable doesn't exist" in lowered or "playwright install" in lowered:
        return (
            "Chromium is not installed for Playwright on this PC. "
            "Install it with playwright install chromium."
        )
    return text


def _title_payload(url: str, title: str) -> str:
    return f"URL: {url}\nTitle: {title}"


async def _wait_stable(page, timeout_ms: int = 1500) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            return


async def _goto_with_retry(page, url: str) -> None:
    last_error: Exception | None = None
    target = (url or "").strip()
    if not target:
        raise ValueError("url is required")
    for attempt in range(_GOTO_RETRIES):
        try:
            response = await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            await _wait_stable(page)
            await _assert_navigation_allowed(page, response, "open")
            return
        except PermissionError:
            raise
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.15 * (attempt + 1))
    raise last_error or RuntimeError(f"Failed to open {target}")


_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-connection",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "content-encoding",
        "content-length",
        "host",
    }
)


def browser_lan_bind_for_url(url: str) -> str:
    """Source IPv4 when Chromium would otherwise follow a VPN default route to a LAN host."""
    scheme = (urlparse(str(url) or "").scheme or "").lower()
    if scheme not in {"http", "https"}:
        return ""
    return lan_http_bind_for_url(url)


async def fetch_browser_lan_url(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any = None,
) -> dict[str, Any]:
    """GET/POST a LAN URL from this PC's on-link RFC1918 address (not the VPN NIC)."""
    import httpx

    cleaned = (url or "").strip()
    bind = browser_lan_bind_for_url(cleaned)
    if not bind:
        raise ValueError("URL is not an on-link RFC1918 browser target")
    req_headers = {
        str(key): str(value)
        for key, value in (headers or {}).items()
        if str(key).lower() not in _HOP_BY_HOP
    }
    kwargs = _with_lan_bind(
        {
            "timeout": 30.0,
            "follow_redirects": False,
            "trust_env": False,
            "verify": False,
            "headers": req_headers,
        },
        cleaned,
        async_client=True,
    )
    async with httpx.AsyncClient(**kwargs) as client:
        response = await client.request(method or "GET", cleaned, content=body)
    out_headers = {
        str(key): str(value)
        for key, value in response.headers.items()
        if str(key).lower() not in _HOP_BY_HOP
    }
    return {"status": response.status_code, "headers": out_headers, "body": response.content}


async def handle_browser_lan_route(route: Any) -> None:
    request = getattr(route, "request", None)
    url = str(getattr(request, "url", "") or "")
    if not browser_lan_bind_for_url(url):
        await route.continue_()
        return
    try:
        headers: dict[str, str] = {}
        getter = getattr(request, "all_headers", None)
        if callable(getter):
            raw = getter()
            if hasattr(raw, "__await__"):
                raw = await raw
            if isinstance(raw, dict):
                headers = {str(key): str(value) for key, value in raw.items()}
        body = getattr(request, "post_data", None)
        payload = await fetch_browser_lan_url(
            url,
            method=str(getattr(request, "method", None) or "GET"),
            headers=headers,
            body=body,
        )
        await route.fulfill(**payload)
    except Exception:
        abort = getattr(route, "abort", None)
        if callable(abort):
            await abort("failed")
            return
        raise


async def install_browser_lan_route(context: Any) -> None:
    """Send on-link RFC1918 Chromium requests from the home NIC, not a VPN default route."""
    route = getattr(context, "route", None)
    if not callable(route):
        return
    await route("**/*", handle_browser_lan_route)


_BROWSER_USE_LAN_FETCH_PATTERNS = (
    {"urlPattern": "http://*"},
    {"urlPattern": "https://*"},
)
_browser_use_lan_sessions: set[int] = set()


def playwright_contexts_from_browser_use_session(session: Any) -> list[Any]:
    """Playwright BrowserContext objects owned by an older Browser Use session."""
    found: list[Any] = []
    seen: set[int] = set()

    def _take(obj: Any) -> None:
        if obj is None or id(obj) in seen:
            return
        if not callable(getattr(obj, "route", None)):
            return
        seen.add(id(obj))
        found.append(obj)

    for name in ("browser_context", "context", "playwright_browser_context", "pw_context"):
        _take(getattr(session, name, None))
    browser = getattr(session, "browser", None)
    for ctx in list(getattr(browser, "contexts", None) or []):
        _take(ctx)
    _take(browser)
    return found


def cdp_clients_from_browser_use_session(session: Any) -> list[Any]:
    """Root CDP clients from current Browser Use (cdp_use / CDP Fetch)."""
    found: list[Any] = []
    seen: set[int] = set()
    for name in ("cdp_client", "_cdp_client_root"):
        try:
            obj = getattr(session, name, None)
        except Exception:
            continue
        if obj is None or id(obj) in seen:
            continue
        if getattr(obj, "send", None) is None and getattr(obj, "register", None) is None:
            continue
        seen.add(id(obj))
        found.append(obj)
    return found


async def _await_maybe(result: Any) -> Any:
    if hasattr(result, "__await__"):
        return await result
    return result


async def _cdp_fetch_call(client: Any, method: str, params: dict[str, Any], session_id: Any = None) -> None:
    fetch = getattr(getattr(client, "send", None), "Fetch", None)
    op = getattr(fetch, method, None)
    if not callable(op):
        return
    kwargs: dict[str, Any] = {"params": params}
    if session_id is not None:
        kwargs["session_id"] = session_id
    try:
        await _await_maybe(op(**kwargs))
        return
    except TypeError:
        pass
    try:
        await _await_maybe(op(params, session_id) if session_id is not None else op(params))
    except TypeError:
        await _await_maybe(op(params))


def _cdp_request_url(event: Any) -> str:
    if not isinstance(event, dict):
        event = getattr(event, "__dict__", {}) or {}
    request = event.get("request") or event.get("Request") or {}
    if not isinstance(request, dict):
        request = getattr(request, "__dict__", {}) or {}
    return str(request.get("url") or event.get("url") or "")


async def handle_cdp_lan_paused(client: Any, event: Any, session_id: Any = None) -> None:
    """CDP Fetch.requestPaused: fulfill on-link LAN from the home NIC; continue the internet."""
    if not isinstance(event, dict):
        event = getattr(event, "__dict__", {}) or {}
    request_id = event.get("requestId") or event.get("request_id")
    if not request_id:
        return
    request = event.get("request") or {}
    if not isinstance(request, dict):
        request = getattr(request, "__dict__", {}) or {}
    url = _cdp_request_url(event)
    if not browser_lan_bind_for_url(url):
        await _cdp_fetch_call(client, "continueRequest", {"requestId": request_id}, session_id)
        return
    try:
        headers = request.get("headers") or {}
        if not isinstance(headers, dict):
            headers = {}
        payload = await fetch_browser_lan_url(
            url,
            method=str(request.get("method") or "GET"),
            headers={str(key): str(value) for key, value in headers.items()},
            body=request.get("postData") or request.get("post_data"),
        )
        response_headers = [
            {"name": str(key), "value": str(value)} for key, value in (payload.get("headers") or {}).items()
        ]
        body = payload.get("body") or b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        await _cdp_fetch_call(
            client,
            "fulfillRequest",
            {
                "requestId": request_id,
                "responseCode": int(payload.get("status") or 200),
                "responseHeaders": response_headers,
                "body": base64.b64encode(bytes(body)).decode("ascii"),
            },
            session_id,
        )
    except Exception:
        await _cdp_fetch_call(
            client,
            "failRequest",
            {"requestId": request_id, "errorReason": "Failed"},
            session_id,
        )


def _register_cdp_request_paused(client: Any) -> None:
    register = getattr(getattr(client, "register", None), "Fetch", None)
    paused = getattr(register, "requestPaused", None)
    if not callable(paused):
        return

    def _on_paused(event: Any, session_id: Any = None) -> None:
        task = handle_cdp_lan_paused(client, event, session_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(task)
            return
        loop.create_task(task)

    paused(_on_paused)


async def _enable_cdp_lan_fetch(client: Any, session_id: Any = None) -> None:
    await _cdp_fetch_call(
        client,
        "enable",
        {"patterns": [dict(item) for item in _BROWSER_USE_LAN_FETCH_PATTERNS]},
        session_id,
    )


async def install_browser_use_lan_intercept(session: Any) -> None:
    """VPN-proof LAN http(s) for Browser Use (Playwright route or CDP Fetch)."""
    if session is None:
        return
    marker = id(session)
    if marker in _browser_use_lan_sessions:
        return
    installed = False
    try:
        for context in playwright_contexts_from_browser_use_session(session):
            await install_browser_lan_route(context)
            installed = True
        clients = cdp_clients_from_browser_use_session(session)
        for client in clients:
            _register_cdp_request_paused(client)
            await _enable_cdp_lan_fetch(client)
            installed = True
        getter = getattr(session, "get_or_create_cdp_session", None)
        focus = getattr(session, "agent_focus_target_id", None)
        root = clients[0] if clients else None
        if callable(getter) and focus and root is not None:
            cdp_session = None
            try:
                cdp_session = await _await_maybe(getter(focus, focus=False))
            except TypeError:
                try:
                    cdp_session = await _await_maybe(getter(focus))
                except Exception:
                    cdp_session = None
            except Exception:
                cdp_session = None
            if cdp_session is not None:
                inner = getattr(cdp_session, "cdp_client", None) or root
                session_id = getattr(cdp_session, "session_id", None)
                if inner is not None:
                    _register_cdp_request_paused(inner)
                    await _enable_cdp_lan_fetch(inner, session_id)
        if installed:
            _browser_use_lan_sessions.add(marker)
    except Exception:
        return


async def _ensure_page(headless: bool):
    global _playwright, _browser, _context, _page, _pages
    if _page:
        return _page
    from playwright.async_api import async_playwright
    from ..config import apply_playwright_browsers_path

    apply_playwright_browsers_path()
    _playwright = await async_playwright().start()
    user_dir = playwright_user_data_dir()
    _context = await _playwright.chromium.launch_persistent_context(
        str(user_dir),
        headless=headless,
        viewport={"width": 1400, "height": 900},
        **chromium_download_launch_kwargs(),
    )
    await install_browser_lan_route(_context)
    _pages = list(_context.pages) or [await _context.new_page()]
    _page = _pages[0]
    return _page


async def _close_browser() -> ToolResult:
    global _playwright, _browser, _context, _page, _pages
    if not _context and not _playwright and not _browser and not _page:
        _pages = []
        return ToolResult(True, "Browser was not open and was not running")
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _context = None
    _playwright = None
    _browser = None
    _page = None
    _pages = []
    return ToolResult(True, "Browser closed")


class BrowserTool(Tool):
    name = "browser"
    description = (
        "Automate Chromium with Playwright using accessibility snapshots rather than coordinates. "
        "Actions: open, snapshot, click, type, fill, press, evaluate, screenshot, tabs, download, "
        "upload, title, close. Use snapshot first, then click by the element's accessible name or CSS selector. "
        "open retries navigation; named clicks try button/link/tab before failing. "
        "open accepts http(s) URLs and local files in the allowed workspace (USB/`D:` HTML/PDF)."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open",
                    "snapshot",
                    "action_frame",
                    "click",
                    "type",
                    "fill",
                    "press",
                    "evaluate",
                    "screenshot",
                    "tabs",
                    "download",
                    "upload",
                    "title",
                    "close",
                ],
            },
            "url": {
                "type": "string",
                "description": "http(s) URL, or a local file path / file:// URI inside the allowed workspace",
            },
            "selector": {"type": "string"},
            "name": {"type": "string", "description": "Accessible name for click/type"},
            "text": {"type": "string"},
            "task": {"type": "string", "description": "Natural-language browser task for Browser Use"},
            "key": {"type": "string"},
            "script": {"type": "string"},
            "path": {
                "type": "string",
                "description": "download/screenshot/upload path. Omit download to use the owner's Downloads folder.",
            },
            "index": {"type": "integer", "description": "Tab index for action=tabs (omit to list)"},
            "headless": {"type": "boolean"},
            "timeout_seconds": {"type": "integer", "default": 15},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    def _allowed(self) -> list[str]:
        raw = self.context_getter() if callable(self.context_getter) else {}
        return live_workspace_roots_from_context(raw)

    def _settings(self) -> AppSettings:
        raw = self.context_getter()
        settings = load_settings()
        if isinstance(raw, AppSettings):
            return raw
        browser = raw.get("browser") if isinstance(raw, dict) else None
        if isinstance(browser, dict):
            merged = settings.model_dump()
            merged["browser"] = {**settings.browser.model_dump(), **browser}
            return AppSettings.model_validate(merged)
        return settings

    async def execute(self, **kwargs: Any) -> ToolResult:
        global _allowed_override
        settings = self._settings()
        action = kwargs.get("action")
        _allowed_override = self._allowed()
        if action == "close":
            async with _lock:
                return await _close_browser()
        if action == "open" and not (kwargs.get("url") or "").strip():
            return ToolResult(False, "", error="url is required")
        if action == "open":
            try:
                kwargs = {**kwargs, "url": resolve_browser_open_url(str(kwargs.get("url") or ""), self._allowed())}
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))
        if action not in _ACTIONS_NEEDING_PAGE:
            return ToolResult(False, "", error=f"Unknown action {action}")

        from ..policy.computer_permissions import evaluate_tool_permissions

        current = ""
        try:
            if _page is not None:
                current = str(getattr(_page, "url", "") or "")
        except Exception:
            current = ""
        gate = evaluate_tool_permissions(
            "browser",
            {"url": browser_permission_url(action, kwargs, current), "action": action},
        )
        if gate.status == "deny":
            return ToolResult(False, "", error=gate.reason)
        if gate.status == "ask":
            return ToolResult(False, "", error=gate.reason or "Permission required before the browser can reach the network.")

        ctx = self.context_getter() if callable(self.context_getter) else {}
        headless = kwargs.get("headless")
        if headless is None:
            if isinstance(ctx, dict):
                headless = bool((ctx.get("browser") or {}).get("headless", False))
            else:
                headless = bool(getattr(getattr(ctx, "browser", None), "headless", False))
        async with _lock:
            try:
                if action == "close":
                    return await _close_browser()
                page = await _ensure_page(bool(headless))
                if action == "open":
                    url = kwargs["url"]
                    await _goto_with_retry(page, url)
                    title = await page.title()
                    return ToolResult(True, f"Opened {page.url}\ntitle={title}")
                if action == "title":
                    await _assert_current_url_allowed(page, "open")
                    return ToolResult(True, f"URL: {page.url}\nTitle: {await page.title()}")
                if action == "snapshot":
                    await _assert_current_url_allowed(page, "open")
                    title = await page.title()
                    a11y = await page.locator("body").inner_text()
                    truncated = a11y[:8000]
                    return ToolResult(
                        True,
                        f"{_title_payload(page.url, title)}\n\n{truncated}",
                        data={"url": page.url, "title": title},
                    )
                if action == "action_frame":
                    await _assert_current_url_allowed(page, "open")
                    # RFC-0172: atomic ActionFrame from DOM/a11y identity (no selector payload).
                    from ..reflex_loop.adapters import snapshot_browser_page

                    frame = await snapshot_browser_page(page)
                    return ToolResult(
                        True,
                        f"ActionFrame {frame.frame_id} nodes={len(frame.nodes)} url={frame.url_or_title}",
                        data={"action_frame": frame.as_dict()},
                    )
                if action == "click":
                    if not kwargs.get("name") and not kwargs.get("selector"):
                        return ToolResult(False, "", error="Provide name or selector")

                    async def _click() -> None:
                        if kwargs.get("name"):
                            name = kwargs["name"]
                            clicked = False
                            for role in ("button", "link", "tab"):
                                try:
                                    await page.get_by_role(role, name=name).first.click(timeout=4000)
                                    clicked = True
                                    break
                                except Exception:
                                    continue
                            if not clicked:
                                await page.get_by_text(name, exact=False).first.click(timeout=8000)
                        else:
                            await page.locator(kwargs["selector"]).first.click(timeout=10000)

                    await _run_and_gate_navigation(page, _click(), "open")
                    page = _page or page
                    return ToolResult(True, f"Clicked. URL now {page.url}")
                if action in {"type", "fill"}:
                    text = kwargs.get("text") or ""
                    if kwargs.get("selector"):
                        locator = page.locator(kwargs["selector"]).first
                    elif kwargs.get("name"):
                        locator = page.get_by_label(kwargs["name"]).first
                    else:
                        locator = page.locator("input, textarea, [contenteditable=true]").first

                    async def _type_or_fill() -> None:
                        if action == "fill":
                            await locator.fill(text)
                        else:
                            await locator.click()
                            await locator.type(text)

                    await _run_and_gate_navigation(page, _type_or_fill(), "open")
                    page = _page or page
                    return ToolResult(True, "Typed into field")
                if action == "press":
                    await _run_and_gate_navigation(
                        page, page.keyboard.press(kwargs.get("key") or "Enter"), "open"
                    )
                    page = _page or page
                    return ToolResult(True, f"Pressed {kwargs.get('key')}")
                if action == "evaluate":
                    async def _eval() -> Any:
                        return await page.evaluate(kwargs.get("script") or "() => document.title")

                    result = await _run_and_gate_navigation(page, _eval(), "open")
                    page = _page or page
                    return ToolResult(True, str(result))
                if action == "screenshot":
                    await _assert_current_url_allowed(page, "open")
                    out = resolve_owner_file_path(
                        kwargs.get("path"),
                        suggested_name="browser.png",
                        allowed=self._allowed(),
                        fallback_dirs=("Pictures", "Downloads"),
                    )
                    out.parent.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(out), full_page=False)
                    encoded = base64.b64encode(out.read_bytes()).decode("ascii")
                    return ToolResult(
                        True,
                        f"Saved screenshot to {out}",
                        data={"path": str(out), "image_base64": encoded[:80] + "...", "attach_image": str(out)},
                    )
                if action == "tabs":
                    pages = list(getattr(getattr(page, "context", None), "pages", None) or [page])
                    raw_index = kwargs.get("index")
                    if raw_index is not None and str(raw_index).strip() != "":
                        try:
                            idx = int(raw_index)
                        except (TypeError, ValueError):
                            return ToolResult(False, "", error="tabs index must be an integer")
                        try:
                            page = await activate_browser_tab(pages, idx, "open")
                        except IndexError as exc:
                            return ToolResult(False, "", error=str(exc))
                    listing = "\n".join(f"{i}: {item.url}" for i, item in enumerate(pages))
                    if raw_index is not None and str(raw_index).strip() != "":
                        return ToolResult(True, f"Switched to tab {int(raw_index)}: {page.url}\n{listing}")
                    return ToolResult(True, listing or "No tabs")
                if action == "download":
                    async def _download() -> Any:
                        async with page.expect_download(timeout=30000) as download_info:
                            if kwargs.get("selector"):
                                await page.locator(kwargs["selector"]).first.click()
                        return await download_info.value

                    download = await _run_and_gate_navigation(page, _download(), "open")
                    dest = resolve_owner_file_path(
                        kwargs.get("path"),
                        suggested_name=getattr(download, "suggested_filename", None) or "download",
                        allowed=self._allowed(),
                        fallback_dirs=("Downloads",),
                    )
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    await download.save_as(str(dest))
                    return ToolResult(True, f"Downloaded to {dest}", data={"path": str(dest)})
                if action == "upload":
                    source = resolve_allowed_path(str(kwargs.get("path") or ""), self._allowed())
                    await _run_and_gate_navigation(
                        page,
                        page.locator(kwargs.get("selector") or "input[type=file]").set_input_files(
                            str(source)
                        ),
                        "open",
                    )
                    return ToolResult(True, f"Uploaded {source}")
                return ToolResult(False, "", error=f"Unknown action {action}")
            except ModuleNotFoundError as exc:
                return ToolResult(False, "", error=_browser_error(exc))
            except Exception as exc:
                return ToolResult(False, "", error=_browser_error(exc))
