import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import * as fs from "fs";
import * as path from "path";

export interface Chat {
  id: string;
  title: string;
  lastMessage: string;
}

export interface Message {
  id: string;
  text: string;
  date: Date;
  senderName: string;
  isFromMe: boolean;
}

const SESSION_PATH = path.join(process.cwd(), ".whatsapp-session");

/**
 * Parses a WhatsApp message timestamp string (e.g. "12:34 PM", "Yesterday", "Mon")
 * into a Date. Returns today's date with the parsed time when a time string is
 * recognisable; otherwise falls back to the current time.
 */
function parseMessageTime(timeStr: string): Date {
  const now = new Date();
  // Match "HH:MM" or "HH:MM AM/PM"
  const match = timeStr.match(/(\d{1,2}):(\d{2})(?:\s*(AM|PM))?/i);
  if (match) {
    let hours = parseInt(match[1] ?? "0", 10);
    const minutes = parseInt(match[2] ?? "0", 10);
    const meridiem = (match[3] ?? "").toUpperCase();
    if (meridiem === "PM" && hours !== 12) hours += 12;
    if (meridiem === "AM" && hours === 12) hours = 0;
    const date = new Date(now);
    date.setHours(hours, minutes, 0, 0);
    return date;
  }
  return now;
}

export class WhatsAppService {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;

  async launch(): Promise<void> {
    this.browser = await chromium.launch({ headless: false });

    const storageStateExists = fs.existsSync(SESSION_PATH);

    this.context = await this.browser.newContext({
      ...(storageStateExists ? { storageState: SESSION_PATH } : {}),
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    });

    this.page = await this.context.newPage();
    await this.page.goto("https://web.whatsapp.com", { waitUntil: "domcontentloaded" });
  }

  async waitForQROrLogin(onQRRequired: () => void): Promise<void> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    // Check if already logged in (chat list visible)
    const loggedIn = await this.page
      .locator('[data-testid="chat-list"]')
      .waitFor({ timeout: 5000 })
      .then(() => true)
      .catch(() => false);

    if (loggedIn) {
      return;
    }

    // Not logged in — QR code scan required
    onQRRequired();

    await this.page.locator('[data-testid="chat-list"]').waitFor({ timeout: 120000 });

    // Save session for next time
    await this.context!.storageState({ path: SESSION_PATH });
  }

  async getRecentChats(limit: number = 5): Promise<Chat[]> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    await this.page.locator('[data-testid="chat-list"]').waitFor({ timeout: 30000 });

    const chatItems = await this.page.locator('[data-testid="cell-frame-container"]').all();
    const chats: Chat[] = [];

    for (let i = 0; i < Math.min(limit, chatItems.length); i++) {
      const item = chatItems[i];
      if (!item) continue;

      const titleEl = item.locator('[data-testid="cell-frame-title"]');
      const lastMsgEl = item.locator('[data-testid="last-msg-status"] + span, .x1iyjqo2 span').first();

      const title = (await titleEl.textContent()) ?? `Chat ${i + 1}`;
      const lastMessage = await lastMsgEl.textContent().catch(() => "");

      chats.push({
        id: String(i),
        title: title.trim(),
        lastMessage: (lastMessage ?? "").trim(),
      });
    }

    return chats;
  }

  async openChat(chatIndex: number): Promise<void> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    const chatItems = await this.page.locator('[data-testid="cell-frame-container"]').all();
    const item = chatItems[chatIndex];
    if (!item) {
      throw new Error(`Chat at index ${chatIndex} not found`);
    }

    await item.click();
    await this.page.locator('[data-testid="conversation-panel-messages"]').waitFor({ timeout: 15000 });
  }

  async getMessages(limit: number = 10): Promise<Message[]> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    await this.page.locator('[data-testid="conversation-panel-messages"]').waitFor({ timeout: 15000 });

    const msgRows = await this.page.locator('[data-testid="msg-container"]').all();
    const messages: Message[] = [];

    const subset = msgRows.slice(-limit);

    for (let i = 0; i < subset.length; i++) {
      const row = subset[i];
      if (!row) continue;

      const isFromMe = await row.evaluate((el) =>
        el.classList.contains("message-out") || el.querySelector(".message-out") !== null
      );

      const textEl = row.locator('[data-testid="msg-container"] .selectable-text span, .copyable-text span').first();
      const text = await textEl.textContent().catch(() => "(media)");

      const timeEl = row.locator('[data-testid="msg-meta"] span').first();
      const timeStr = await timeEl.textContent().catch(() => "");

      // Sender name (only shown in group chats)
      const senderEl = row.locator('[data-testid="msg-container"] .e1gr2w1z span').first();
      const senderName = await senderEl.textContent().catch(() => isFromMe ? "Me" : "Them");

      messages.push({
        id: String(i),
        text: (text ?? "(media)").trim(),
        date: parseMessageTime(timeStr ?? ""),
        senderName: (senderName ?? (isFromMe ? "Me" : "Them")).trim() || (isFromMe ? "Me" : "Them"),
        isFromMe,
      });
    }

    return messages;
  }

  async sendMessage(text: string): Promise<void> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    const inputBox = this.page.locator('[data-testid="conversation-compose-box-input"]');
    await inputBox.click();
    await inputBox.fill(text);
    await this.page.keyboard.press("Enter");
  }

  async close(): Promise<void> {
    if (this.context) {
      await this.context.storageState({ path: SESSION_PATH }).catch(() => {});
    }
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
      this.context = null;
      this.page = null;
    }
  }
}
