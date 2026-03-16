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
 * Helper function to get selector from environment variable with fallback
 */
function getSelector(envKey: string, fallback: string): string {
  return process.env[envKey] || fallback;
}

// WhatsApp Web Selectors - configurable via .env
const SELECTORS = {
  CHAT_LIST: () => getSelector("WA_CHAT_LIST_SELECTOR", '[aria-label="Chat list"]'),
  CHAT_ROW: () => getSelector("WA_CHAT_ROW_SELECTOR", 'div[role="row"]'),
  MESSAGE_ROW: () => getSelector("WA_MESSAGE_ROW_SELECTOR", 'div[role="row"]'),
  MESSAGE_TEXT: () => getSelector("WA_MESSAGE_TEXT_SELECTOR", 'span[data-testid="selectable-text"]'),
  MESSAGE_TIME: () => getSelector("WA_MESSAGE_TIME_SELECTOR", 'span.x1c4vz4f.x2lah0s'),
  SENDER_NAME: () => getSelector("WA_SENDER_NAME_SELECTOR", '._ahxt'),
  CONVERSATION_PANEL: () => getSelector("WA_CONVERSATION_PANEL_SELECTOR", '[data-testid="conversation-panel-messages"]'),
  QR_CODE: () => getSelector("WA_QR_CODE_SELECTOR", '[data-testid="qrcode"]'),
  INPUT_BOX: () => getSelector("WA_INPUT_BOX_SELECTOR", '[data-testid="conversation-compose-box-input"]'),
};

/**
 * Parses a WhatsApp message timestamp string in "HH:MM" or "HH:MM AM/PM" format
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
    this.browser = await chromium.launch({
      headless: false,
      args: [
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
      ]
    });

    const storageStateExists = fs.existsSync(SESSION_PATH);

    this.context = await this.browser.newContext({
      ...(storageStateExists ? { storageState: SESSION_PATH } : {}),
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      viewport: { width: 1280, height: 720 },
      locale: 'en-US',
      timezoneId: 'America/New_York',
    });

    this.page = await this.context.newPage();

    // Remove webdriver property to avoid detection
    await this.page.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', {
        get: () => false,
      });
    });

    await this.page.goto("https://web.whatsapp.com", { waitUntil: "domcontentloaded" });
  }

  async waitForQROrLogin(onQRRequired: () => void): Promise<void> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    const chatListLocator = this.page.locator(SELECTORS.CHAT_LIST());
    const qrLocator = this.page.locator(SELECTORS.QR_CODE());

    // First, give the chat list a reasonably long time to appear (already logged-in case)
    const loggedIn = await chatListLocator
      .waitFor({ timeout: 15000 })
      .then(() => true)
      .catch(() => false);

    if (loggedIn) {
      return;
    }

    // If chat list didn't appear, only treat this as "QR required" if the QR/login UI is visible
    const qrVisible = await qrLocator
      .waitFor({ timeout: 15000 })
      .then(() => true)
      .catch(() => false);

    if (qrVisible) {
      // Not logged in — QR code scan required
      onQRRequired();
    }

    await chatListLocator.waitFor({ timeout: 120000 });

    // Wait a bit for WhatsApp to fully initialize before saving session
    await this.page.waitForTimeout(2000);

    // Save session for next time
    await this.context!.storageState({ path: SESSION_PATH });
  }

  async getRecentChats(limit: number = 5): Promise<Chat[]> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    await this.page.locator(SELECTORS.CHAT_LIST()).waitFor({ timeout: 30000 });

    const chatItems = await this.page.locator(`${SELECTORS.CHAT_LIST()} > ${SELECTORS.CHAT_ROW()}`).all();
    const chats: Chat[] = [];

    for (let i = 0; i < Math.min(limit, chatItems.length); i++) {
      const item = chatItems[i];
      if (!item) continue;

      // Get chat title from the span with title attribute
      const titleSpans = item.locator('span[title]');
      const titleCount = await titleSpans.count();

      let title = `Chat ${i + 1}`;
      let lastMessage = "";

      if (titleCount > 0) {
        // First span[title] is usually the chat name
        title = (await titleSpans.first().getAttribute('title')) ?? `Chat ${i + 1}`;

        // Second span[title] is usually the last message
        if (titleCount > 1) {
          lastMessage = (await titleSpans.nth(1).getAttribute('title')) ?? "";
        }
      }

      chats.push({
        id: String(i),
        title: title.trim(),
        lastMessage: lastMessage.trim(),
      });
    }

    return chats;
  }

  async openChat(chatIndex: number): Promise<void> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    const chatItems = await this.page.locator(`${SELECTORS.CHAT_LIST()} > ${SELECTORS.CHAT_ROW()}`).all();
    const item = chatItems[chatIndex];
    if (!item) {
      throw new Error(`Chat at index ${chatIndex} not found`);
    }

    await item.click();
    await this.page.locator(SELECTORS.CONVERSATION_PANEL()).waitFor({ timeout: 15000 });
  }

  async getMessages(limit: number = 10): Promise<Message[]> {
    if (limit <= 0) {
      return [];
    }
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    await this.page.locator(SELECTORS.CONVERSATION_PANEL()).waitFor({ timeout: 15000 });

    const msgRows = this.page.locator(SELECTORS.MESSAGE_ROW()).filter({ has: this.page.locator(`${SELECTORS.MESSAGE_ROW()} div[data-id]`) });
    const messages: Message[] = [];

    const totalCount = await msgRows.count();
    const startIndex = Math.max(0, totalCount - limit);

    for (let i = startIndex; i < totalCount; i++) {
      const row = msgRows.nth(i);

      const isFromMe = await row.evaluate((el) =>
        el.classList.contains("message-out") || el.querySelector(".message-out") !== null
      );

      const textEl = row.locator(SELECTORS.MESSAGE_TEXT()).first();
      const text = await textEl.textContent().catch(() => "(media)");

      // Extract time from the visible timestamp
      const timeEl = row.locator(SELECTORS.MESSAGE_TIME()).last();
      const timeStr = await timeEl.textContent().catch(() => "");

      // Sender name (shown for incoming messages in group chats)
      const senderEl = row.locator(SELECTORS.SENDER_NAME()).first();
      const senderName = await senderEl.textContent().catch(() => isFromMe ? "Me" : "Them");

      messages.push({
        id: String(i - startIndex),
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

    const inputBox = this.page.locator(SELECTORS.INPUT_BOX());
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
