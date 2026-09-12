/**
 * One-shot WhatsApp actions against the already-paired wappmcp profile.
 * Usage: node whatsapp-action.mjs '<json>'
 * Actions: me | lookup | send_text | send_media
 */
import { WhatsAppSession } from "./node_modules/wappmcp/dist/index.js";

const emit = (payload) => {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
};

const fail = (message, code = 1) => {
  emit({ ok: false, error: message });
  process.exit(code);
};

let request;
try {
  request = JSON.parse(process.argv[2] || "{}");
} catch {
  fail("Invalid JSON request");
}

const action = String(request.action || "");
if (!action) fail("Missing action");

let session;
let stopping = false;

async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  try {
    await session?.destroy();
  } finally {
    process.exit(code);
  }
}

process.on("SIGINT", () => void stop(1));
process.on("SIGTERM", () => void stop(1));

try {
  session = new WhatsAppSession({ headless: true });
  await session.start();
  await session.waitForReady(120_000);

  if (action === "me") {
    const me = await session.getMe();
    emit({
      ok: true,
      id: me.id,
      name: me.name || me.pushname || "Jarvis",
      number: me.number || "",
      pushname: me.pushname || "",
    });
    await stop(0);
  }

  if (action === "lookup") {
    const q = String(request.q || request.phone || "").trim();
    if (!q) fail("Missing phone number");
    const result = await session.lookupNumber(q);
    emit({ ok: true, ...result });
    await stop(0);
  }

  if (action === "send_text") {
    const chatId = String(request.chatId || "").trim();
    const text = String(request.text || "").trim();
    if (!chatId || !text) fail("chatId and text are required");
    const messageId = await session.sendMessage(chatId, text);
    emit({ ok: true, messageId, chatId });
    await stop(0);
  }

  if (action === "send_media") {
    const chatId = String(request.chatId || "").trim();
    const path = String(request.path || "").trim();
    const caption = request.caption ? String(request.caption) : undefined;
    if (!chatId || !path) fail("chatId and path are required");
    const messageId = await session.sendMediaFromPath(chatId, path, caption);
    emit({ ok: true, messageId, chatId });
    await stop(0);
  }

  fail(`Unknown action: ${action}`);
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
}
