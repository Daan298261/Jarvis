import { WhatsAppSession } from "./node_modules/wappmcp/dist/index.js";

const emit = (state, extra = {}) => {
  process.stdout.write(`${JSON.stringify({ state, ...extra })}\n`);
};

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

process.on("SIGINT", () => void stop(0));
process.on("SIGTERM", () => void stop(0));

try {
  emit("starting");
  session = new WhatsAppSession({
    headless: true,
    onQr: (qr) => emit("pairing", { qr }),
  });
  await session.start();
  emit("connected");
  await stop(0);
} catch (error) {
  emit("failed", { error: error instanceof Error ? error.message : String(error) });
  await stop(1);
}
