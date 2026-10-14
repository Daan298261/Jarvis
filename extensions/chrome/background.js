import {pageOperation} from "./page.js";
import {adRules} from "./ad-rules.js";

const HOST = "com.anzu.website_connector";
const ACTIONS = new Set(["chrome_snapshot", "chrome_find", "chrome_click", "chrome_fill", "chrome_block_ads", "chrome_frames", "chrome_upload", "chrome_download"]);
let shared = null;
let port = null;
let lastError = "";
let chain = Promise.resolve();

async function clearRules() {
  const rules = await chrome.declarativeNetRequest.getSessionRules();
  await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds: rules.map(rule => rule.id)});
}

async function revoke() {
  const previous = shared;
  shared = null;
  const old = port;
  port = null;
  old?.disconnect();
  if (previous) {
    try { await chrome.scripting.executeScript({target:{tabId:previous.id,allFrames:true},func:() => {globalThis.__anzuUpload=null; globalThis.__anzuTargets=null;}}); }
    catch { /* Navigated/closed or no longer permitted; the old document is gone. */ }
  }
  await clearRules();
  await chrome.action.setBadgeText({text: ""});
}

async function execute(request) {
  if (!shared || !ACTIONS.has(request.action)) throw new Error("No shared tab or unsupported operation");
  if (Date.now() / 1000 >= request.expires) throw new Error("Command expired");
  const target = shared;
  const tab = await chrome.tabs.get(target.id);
  if (shared !== target) throw new Error("Tab sharing ended");
  if (tab.url !== target.url || request.url !== target.url) throw new Error("Tab URL changed or request targets a different page");
  if (request.action === "chrome_frames") {
    const frames = await chrome.webNavigation.getAllFrames({tabId: target.id});
    return {frames: await Promise.all(frames.filter(frame => /^https?:/.test(frame.url)).map(async frame => {
      const url=new URL(frame.url);
      const permitted=!url.username && !url.password && (url.origin === new URL(target.url).origin || target.include_frames) && await chrome.permissions.contains({origins:[`${url.origin}/*`]});
      return {frame_id:frame.frameId, ...(permitted ? {url:frame.url} : {origin:url.origin}), permitted};
    }))};
  }
  if (request.action === "chrome_block_ads") {
    if (typeof request.enabled !== "boolean") throw new Error("enabled must be a boolean");
    const filters = request.enabled ? await adRules(target.id) : {rules: [], count: 0};
    const existing = await chrome.declarativeNetRequest.getSessionRules();
    await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds: existing.map(rule => rule.id), addRules: filters.rules});
    // Revocation/navigation may have raced the async API call: clear any rules it added.
    if (shared !== null && shared.id === target.id && shared.url === target.url) {
      return {url: target.url, enabled: request.enabled, domain_count: filters.count, source: filters.source, scope: "shared tab until navigation, revocation or browser restart"};
    }
    await clearRules();
    throw new Error("Tab sharing ended");
  }
  const frameId = request.frame_id || 0;
  if (frameId !== 0) {
    const frames = await chrome.webNavigation.getAllFrames({tabId: target.id});
    const frame = frames.find(frame => frame.frameId === frameId);
    if (!frame || frame.url !== request.frame_url || !/^https?:/.test(frame.url)) throw new Error("Frame navigated or is unavailable");
    if (new URL(frame.url).origin !== new URL(target.url).origin && !target.include_frames) throw new Error("Share this tab with embedded websites enabled before using that frame");
    if (!await chrome.permissions.contains({origins: [`${new URL(frame.url).origin}/*`]})) throw new Error("Grant this embedded site's access in the extension before using the frame");
  }
  if (shared !== target || Date.now() / 1000 >= request.expires) throw new Error("Sharing ended or command expired");
  const results = await chrome.scripting.executeScript({target: {tabId: target.id, frameIds: [frameId]}, func: pageOperation, args: [request]});
  if (results[0]?.error) throw new Error(results[0].error.message || "Page operation failed");
  if (!results[0]?.result) throw new Error("Page returned no result");
  if (request.action === "chrome_download") {
    if (shared !== target) throw new Error("Sharing ended");
    const id = await chrome.downloads.download({url: results[0].result.download_url, conflictAction: "uniquify", saveAs: false});
    while (Date.now() / 1000 < request.expires) {
      if (shared !== target) {await chrome.downloads.cancel(id); throw new Error("Sharing ended; download cancelled");}
      const [item] = await chrome.downloads.search({id});
      if (item?.state === "complete") return {download_id: id, state: item.state, filename: item.filename, url: item.finalUrl || item.url, size: item.fileSize};
      if (item?.state === "interrupted") throw new Error(`Download interrupted: ${item.error || "unknown reason"}`);
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    return {download_id: id, state: "in_progress", verify_before_reporting_completion: true};
  }
  return results[0].result;
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("popup.html")) return false;
  (async () => {
    if (message.action === "status") return {shared, error: lastError, connected: Boolean(port)};
    if (message.action === "revoke") {await revoke(); return {shared: null};}
    if (message.action !== "share") throw new Error("Unknown connector command");
    const tab = await chrome.tabs.get(message.tabId);
    const url = new URL(tab.url);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("Share an HTTP(S) website tab");
    if (!await chrome.permissions.contains({origins: [`${url.origin}/*`]})) throw new Error("Site access was not granted");
    await revoke();
    shared = {id: tab.id, url: tab.url, title: tab.title, include_frames:Boolean(message.include_frames)};
    lastError = "";
    const connection = chrome.runtime.connectNative(HOST);
    port = connection;
    connection.onDisconnect.addListener(() => {
      const error = chrome.runtime.lastError?.message || "Disconnected";
      if (port === connection) {lastError = error; void revoke();}
    });
    connection.onMessage.addListener(request => {
      chain = chain.catch(() => {}).then(async () => {
        if (connection !== port) return;
        let reply;
        try {reply = {id: request.id, success: true, data: await execute(request)};}
        catch (error) {reply = {id: request.id, success: false, error: error.message};}
        if (connection === port) connection.postMessage(reply);
      });
    });
    connection.postMessage({type: "shared", ...shared});
    await chrome.action.setBadgeText({text: "ON"});
    return {shared, connected: true};
  })().then(respond, error => respond({error: error.message}));
  return true;
});

chrome.tabs.onUpdated.addListener((id, change) => {
  if (shared?.id === id && (change.url || change.status === "loading")) void revoke();
});
chrome.tabs.onRemoved.addListener(id => {if (shared?.id === id) void revoke();});
chrome.runtime.onStartup.addListener(() => {void revoke();});
// A service-worker restart also forgets sharing and removes leftover session rules.
void clearRules();
