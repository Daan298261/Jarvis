import fs from "node:fs/promises";
import path from "node:path";
import { loadRawConfig, saveConfig } from "./node_modules/@codefuturist/email-mcp/dist/config/loader.js";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const payload = await readStdin();
const configPath = path.resolve(payload.configPath);
const tempPath = path.resolve(payload.tempPath);
let config = {
  settings: { rate_limit: 10, read_only: false },
  accounts: [],
};

try {
  await fs.access(configPath);
  config = await loadRawConfig(configPath);
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

const account = payload.account;
const index = config.accounts.findIndex(
  (item) => item.name === account.name || item.email.toLowerCase() === account.email.toLowerCase(),
);
if (index >= 0) config.accounts[index] = account;
else config.accounts.push(account);

await saveConfig(config, tempPath);
await fs.chmod(tempPath, 0o600).catch(() => undefined);
process.stdout.write("ok");
