// Runs only in Chrome's isolated extension world, never the site's JS world.
export function pageOperation(request) {
  if (Date.now() / 1000 >= request.expires) throw new Error("Command expired");
  if (location.href !== request.url) throw new Error("Tab navigated; share it again");
  const visible = el => {
    const style = getComputedStyle(el);
    return el.isConnected && el.getClientRects().length > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const label = el => (el.getAttribute("aria-label") || el.innerText || el.getAttribute("placeholder") || el.getAttribute("name") || "").trim().slice(0, 200);
  if (request.action === "chrome_snapshot") {
    const prefix = crypto.randomUUID();
    const nodes = new Map();
    const controls = [];
    for (const el of document.querySelectorAll("a[href],button,input,textarea,select,[role=button]")) {
      if (!visible(el) || el.disabled || el.matches('input[type=password],input[type=hidden]')) continue;
      const id = `${prefix}:${controls.length}`;
      const fingerprint = [label(el), el.getAttribute("type"), el.getAttribute("href")].join("\n");
      nodes.set(id, {el, fingerprint});
      controls.push({target_id: id, name: label(el), role: el.getAttribute("role") || el.tagName.toLowerCase(), href: el.tagName === "A" ? el.href : undefined});
      if (controls.length >= 200) break;
    }
    globalThis.__anzuTargets = nodes;
    return {url: location.href, title: document.title, untrusted_page_content: true, text: (document.body?.innerText || "").slice(0, 16000), controls};
  }
  if (request.action === "chrome_find") {
    const text = document.body?.innerText || "";
    const needle = String(request.text || "").trim().toLowerCase();
    if (!needle) throw new Error("Search text is required");
    const lower = text.toLowerCase();
    const matches = [];
    let start = 0;
    while (matches.length < 20) {
      const index = lower.indexOf(needle, start);
      if (index < 0) break;
      matches.push(text.slice(Math.max(0, index - 150), index + needle.length + 250));
      start = index + needle.length;
    }
    return {url: location.href, title: document.title, untrusted_page_content: true, matches, limit: 20};
  }
  const observed = globalThis.__anzuTargets?.get(request.target_id);
  const el = observed?.el;
  if (!el || !visible(el) || el.disabled || [label(el), el.getAttribute("type"), el.getAttribute("href")].join("\n") !== observed.fingerprint) {
    throw new Error("Stale or unavailable target; take a fresh snapshot");
  }
  if (request.action === "chrome_click") {
    if (el.tagName === "A") {
      const destination = new URL(el.href);
      if (destination.origin !== location.origin || !["http:", "https:"].includes(destination.protocol) || el.target === "_blank" || el.hasAttribute("download")) {
        throw new Error("Open that link manually and share its tab before using ANZU");
      }
    }
    el.click();
  } else if (request.action === "chrome_fill") {
    if (!el.matches("input,textarea") || el.readOnly || (el.tagName === "INPUT" && !["text", "search", "email", "url", "tel", "number"].includes(el.type))) {
      throw new Error("Target is not an editable non-secret text field");
    }
    const prototype = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(el, String(request.text || "").slice(0, 16000));
    el.dispatchEvent(new Event("input", {bubbles: true}));
    el.dispatchEvent(new Event("change", {bubbles: true}));
  } else {
    throw new Error("Unsupported page operation");
  }
  // A mutation consumes the snapshot; observe the resulting state before acting again.
  globalThis.__anzuTargets = new Map();
  return {url: location.href, action: request.action, dispatched: true, verify_with_snapshot: true};
}
