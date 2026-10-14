import assert from "node:assert/strict";
import {test} from "node:test";

function event() {
  const handlers = [];
  return {handlers, addListener(handler) {handlers.push(handler);}};
}
const updated = event();
const removed = event();
const messages = event();
let rules = [];
let native;
let tab = {id: 7, url: "https://example.test/", title: "Example"};
let injections = 0;
let allowed = true;
globalThis.chrome = {
  declarativeNetRequest: {
    async getSessionRules() {return rules;},
    async updateSessionRules({removeRuleIds = [], addRules = []}) {rules = rules.filter(rule => !removeRuleIds.includes(rule.id)).concat(addRules);}
  },
  tabs: {async get() {return tab;}, onUpdated: updated, onRemoved: removed},
  scripting: {async executeScript() {injections++; return [{result: {text: "hello"}}];}},
  action: {async setBadgeText() {}},
  permissions: {async contains() {return allowed;}},
  runtime: {
    id: "test", onMessage: messages, onStartup: event(),
    getURL(path) {return `chrome-extension://test/${path}`;},
    connectNative() {
      native = {onDisconnect: event(), onMessage: event(), replies: [], disconnect() {}, postMessage(value) {this.replies.push(value);}};
      return native;
    }
  }
};
await import("../background.js");
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
async function message(value) {
  return await new Promise(resolve => messages.handlers[0](value, {id: "test", url: "chrome-extension://test/popup.html"}, resolve));
}
async function command(action, extra = {}) {
  const connection = native;
  const request = {id: "a".repeat(32), action, url: tab.url, expires: Date.now() / 1000 + 5, ...extra};
  connection.onMessage.handlers[0](request);
  await tick();
  return connection.replies.at(-1);
}

test("shared tab commands, URL guard, expiry and tab-scoped reversible ad rules", async () => {
  await tick();
  assert.equal((await message({action: "share", tabId: 7})).connected, true);
  assert.equal((await command("chrome_snapshot")).success, true);
  assert.equal(injections, 1);
  assert.equal((await command("chrome_snapshot", {url: "https://other.test/"})).success, false);
  assert.equal((await command("chrome_click", {expires: 0})).success, false);
  assert.equal((await command("evaluate", {script: "alert(1)"})).success, false);
  assert.equal(injections, 1);
  assert.equal((await command("chrome_block_ads", {enabled: true})).success, true);
  assert.equal(rules.length, 4);
  assert.ok(rules.every(rule => JSON.stringify(rule.condition.tabIds) === "[7]"));
  assert.equal((await command("chrome_block_ads", {enabled: false})).success, true);
  assert.equal(rules.length, 0);
  await command("chrome_block_ads", {enabled: true});
  updated.handlers[0](7, {url: "https://example.test/new"});
  await tick();
  assert.equal((await message({action: "status"})).shared, null);
  assert.equal(rules.length, 0);
});

test("site permission denied and explicit revocation", async () => {
  allowed = false;
  assert.match((await message({action: "share", tabId: 7})).error, /not granted/);
  allowed = true;
  await message({action: "share", tabId: 7});
  await command("chrome_block_ads", {enabled: true});
  await message({action: "revoke"});
  assert.equal((await message({action: "status"})).shared, null);
  assert.equal(rules.length, 0);
});

test("host disconnect and tab closure clear rules and sharing", async () => {
  await message({action: "share", tabId: 7});
  await command("chrome_block_ads", {enabled: true});
  native.onDisconnect.handlers[0]();
  await tick();
  assert.equal((await message({action: "status"})).connected, false);
  assert.equal(rules.length, 0);
  await message({action: "share", tabId: 7});
  removed.handlers[0](7);
  await tick();
  assert.equal((await message({action: "status"})).shared, null);
});

test("ordinary web pages cannot send control messages", () => {
  const handled = messages.handlers[0]({action: "share", tabId: 7}, {id: "test", tab: {id: 7}, url: tab.url}, () => {throw new Error("must not respond");});
  assert.equal(handled, false);
});
