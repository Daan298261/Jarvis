// Runs only in Chrome's isolated extension world, never the site's JS world.
export function pageOperation(request) {
  if (Date.now() / 1000 >= request.expires) throw new Error("Command expired");
  if (location.href !== (request.frame_url || request.url)) throw new Error("Tab or frame navigated; take a fresh snapshot");
  const visible = el => {
    const style = getComputedStyle(el);
    return el.isConnected && el.getClientRects().length > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const label = el => (el.getAttribute("aria-label") || el.innerText || el.getAttribute("placeholder") || el.getAttribute("name") || "").trim().slice(0, 200);
  const roots = [document];
  for (let index = 0; index < roots.length; index++) {
    for (const el of roots[index].querySelectorAll("*")) if (el.shadowRoot) roots.push(el.shadowRoot);
  }
  const pageText = () => roots.map(root => root === document ? document.body?.innerText || "" : [...root.children].filter(visible).map(el => el.innerText || "").join("\n")).join("\n");
  if (request.action === "chrome_snapshot") {
    const prefix = [...crypto.getRandomValues(new Uint8Array(16))].map(byte => byte.toString(16).padStart(2, "0")).join("");
    const nodes = new Map();
    const controls = [];
    for (const el of roots.flatMap(root => [...root.querySelectorAll("a[href],button,input,textarea,select,[role=button]")])) {
      if (!visible(el) || el.disabled || el.matches('input[type=password],input[type=hidden]')) continue;
      const id = `${prefix}:${controls.length}`;
      const fingerprint = [label(el), el.getAttribute("type"), el.getAttribute("href")].join("\n");
      nodes.set(id, {el, fingerprint});
      controls.push({target_id: id, name: label(el), role: el.getAttribute("role") || el.tagName.toLowerCase(), input_type: el.type, href: el.tagName === "A" ? el.href : undefined});
      if (controls.length >= 200) break;
    }
    globalThis.__anzuTargets = nodes;
    return {url: location.href, frame_id: request.frame_id || 0, title: document.title, untrusted_page_content: true, text: pageText().slice(0, 16000), controls, open_shadow_roots: roots.length - 1};
  }
  if (request.action === "chrome_find") {
    const text = pageText();
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
  if (request.action === "chrome_upload" && request.stage !== "begin") {
    const upload = globalThis.__anzuUpload;
    if (!upload || upload.id !== request.upload_id || !visible(upload.el)) throw new Error("Upload target expired");
    if (request.stage === "chunk") {
      const bytes = Uint8Array.from(atob(request.chunk), character => character.charCodeAt(0));
      if (upload.received + bytes.length > upload.size) throw new Error("Upload exceeds declared size");
      upload.parts.push(bytes);
      upload.received += bytes.length;
      return {received: upload.received};
    }
    if (request.stage !== "finish" || upload.received !== upload.size) throw new Error("Incomplete upload");
    const transfer = new DataTransfer();
    transfer.items.add(new File(upload.parts, upload.name, {type: upload.mime}));
    upload.el.files = transfer.files;
    upload.el.dispatchEvent(new Event("input", {bubbles: true}));
    upload.el.dispatchEvent(new Event("change", {bubbles: true}));
    globalThis.__anzuUpload = null;
    globalThis.__anzuTargets = new Map();
    return {selected_file: upload.name, size: upload.size, verify_with_snapshot: true};
  }
  const observed = globalThis.__anzuTargets?.get(request.target_id);
  const el = observed?.el;
  if (!el || !visible(el) || el.disabled || [label(el), el.getAttribute("type"), el.getAttribute("href")].join("\n") !== observed.fingerprint) {
    throw new Error("Stale or unavailable target; take a fresh snapshot");
  }
  if (request.action === "chrome_upload") {
    if (!el.matches('input[type=file]') || !Number.isInteger(request.size) || request.size < 0 || request.size > 20 * 1024 * 1024 || !request.upload_id) throw new Error("Invalid upload target or size");
    globalThis.__anzuUpload = {id: request.upload_id, el, size: request.size, name: request.filename, mime: request.mime, parts: [], received: 0};
    return {ready: true};
  }
  if (request.action === "chrome_download") {
    if (el.tagName !== "A" || el.href !== request.download_url) throw new Error("Download must match an observed link");
    const url = new URL(el.href);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("Only HTTP(S) downloads without URL credentials are allowed");
    return {download_url: el.href};
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
