import {pageOperation} from "./page.js";

const HOST = "com.anzu.website_connector";
const ACTIONS = new Set(["chrome_snapshot", "chrome_find", "chrome_click", "chrome_fill", "chrome_block_ads"]);
let shared = null;
let port = null;
let lastError = "";
let chain = Promise.resolve();
const AD_DOMAINS = ["doubleclick.net", "googlesyndication.com", "googleadservices.com", "adnxs.com"];

async function clearRules() {
  const rules = await chrome.declarativeNetRequest.getSessionRules();
  await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds: rules.map(rule => rule.id)});
}

async function revoke() {
  shared = null;
  const old = port;
  port = null;
  old?.disconnect();
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
  if (request.action === "chrome_block_ads") {
    if (typeof request.enabled !== "boolean") throw new Error("enabled must be a boolean");
    const rules = request.enabled ? AD_DOMAINS.map((domain, index) => ({
      id: index + 1, priority: 1, action: {type: "block"},
      condition: {urlFilter: `||${domain}^`, tabIds: [target.id], resourceTypes: ["script", "image", "xmlhttprequest", "sub_frame", "media", "ping"]}
    })) : [];
    await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds: AD_DOMAINS.map((_, i) => i + 1), addRules: rules});
    // Revocation/navigation may have raced the async API call: clear any rules it added.
    if (shared !== null && shared.id === target.id && shared.url === target.url) {
      return {url: target.url, enabled: request.enabled, domains: AD_DOMAINS, scope: "shared tab until navigation, revocation or browser restart"};
    }
    await clearRules();
    throw new Error("Tab sharing ended");
  }
  const results = await chrome.scripting.executeScript({target: {tabId: target.id}, func: pageOperation, args: [request]});
  if (results[0]?.error) throw new Error(results[0].error.message || "Page operation failed");
  if (!results[0]?.result) throw new Error("Page returned no result");
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
    shared = {id: tab.id, url: tab.url, title: tab.title};
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
