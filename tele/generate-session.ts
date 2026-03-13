import "dotenv/config";
import { TelegramClient } from "telegram";
import { StringSession } from "telegram/sessions/index.js";
import * as readline from "readline";

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

function question(prompt: string): Promise<string> {
  return new Promise((resolve) => {
    rl.question(prompt, (answer) => {
      resolve(answer);
    });
  });
}

async function main() {
  console.log("=== Telegram String Session Generator ===\n");

  const apiId = process.env.TELEGRAM_API_ID;
  const apiHash = process.env.TELEGRAM_API_HASH;

  if (!apiId || !apiHash) {
    console.error("Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env file");
    console.error("Get them from https://my.telegram.org/apps");
    process.exit(1);
  }

  console.log(`Using API ID: ${apiId}`);
  console.log(`Using API Hash: ${apiHash.substring(0, 4)}...${apiHash.substring(apiHash.length - 4)}\n`);

  const stringSession = new StringSession("");
  const client = new TelegramClient(stringSession, parseInt(apiId), apiHash, {
    connectionRetries: 5,
  });

  await client.start({
    phoneNumber: async () => await question("Enter your phone number (with country code, e.g., +1234567890): "),
    password: async () => await question("Enter your 2FA password (if enabled): "),
    phoneCode: async () => await question("Enter the code you received: "),
    onError: (err) => console.log("Error:", err),
  });

  console.log("\n✅ Successfully authenticated!");
  console.log("\nYour String Session:");
  console.log("========================");
  console.log(client.session.save());
  console.log("========================");
  console.log("\nCopy the above string session and add it to your .env file as TELEGRAM_STRING_SESSION");

  rl.close();
  process.exit(0);
}

main().catch((error) => {
  console.error("Error:", error.message);
  rl.close();
  process.exit(1);
});
