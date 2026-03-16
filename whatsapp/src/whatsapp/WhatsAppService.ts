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
  MESSAGE_CONTAINER: () => getSelector("WA_MESSAGE_CONTAINER_SELECTOR", '[data-pre-plain-text]'),
  MESSAGE_META_ATTR: () => getSelector("WA_MESSAGE_META_ATTR", 'data-pre-plain-text'),
  MESSAGE_TEXT: () => getSelector("WA_MESSAGE_TEXT_SELECTOR", 'span[data-testid="selectable-text"]'),
  MESSAGE_OUTGOING: () => getSelector("WA_MESSAGE_OUTGOING_SELECTOR", '.message-out'),
  MESSAGE_OUTGOING_DATA_ATTR: () => getSelector("WA_MESSAGE_OUTGOING_DATA_ATTR", 'data-id'),
  MESSAGE_OUTGOING_DATA_PREFIX: () => getSelector("WA_MESSAGE_OUTGOING_DATA_PREFIX", 'true_'),
  QR_CODE: () => getSelector("WA_QR_CODE_SELECTOR", '[data-testid="qrcode"]'),
  INPUT_BOX: () => getSelector("WA_INPUT_BOX_SELECTOR", '[data-testid="conversation-compose-box-input"]'),
};

/**
 * Parses the data-pre-plain-text attribute from a WhatsApp message element.
 * Format: "[2:04 pm, 16/03/2026] SenderName: "
 */
function parsePrePlainText(attr: string): { date: Date; senderName: string } {
  const match = attr.match(/\[(.+?),\s*(.+?)\]\s*(.+?):\s*$/);
  if (!match) {
    return { date: new Date(), senderName: "" };
  }

  const timeStr = match[1]!;
  const dateStr = match[2]!;
  const senderName = match[3]!.trim();

  const date = new Date();

  const dateParts = dateStr.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (dateParts) {
    date.setFullYear(parseInt(dateParts[3]!, 10));
    date.setMonth(parseInt(dateParts[2]!, 10) - 1);
    date.setDate(parseInt(dateParts[1]!, 10));
  }

  const timeMatch = timeStr.match(/(\d{1,2}):(\d{2})(?:\s*(am|pm))?/i);
  if (timeMatch) {
    let hours = parseInt(timeMatch[1]!, 10);
    const minutes = parseInt(timeMatch[2]!, 10);
    const meridiem = (timeMatch[3] ?? "").toUpperCase();
    if (meridiem === "PM" && hours !== 12) hours += 12;
    if (meridiem === "AM" && hours === 12) hours = 0;
    date.setHours(hours, minutes, 0, 0);
  }

  return { date, senderName };
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
    await this.page.locator(SELECTORS.MESSAGE_CONTAINER()).first().waitFor({ timeout: 15000 });
  }

  async getMessages(limit: number = 10): Promise<Message[]> {
    if (limit <= 0) {
      return [];
    }
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    await this.page.locator(SELECTORS.MESSAGE_CONTAINER()).first().waitFor({ timeout: 15000 });

    const msgEls = this.page.locator(SELECTORS.MESSAGE_CONTAINER());

    const messages: Message[] = [];

    const totalCount = await msgEls.count();
    const startIndex = Math.max(0, totalCount - limit);

    for (let i = startIndex; i < totalCount; i++) {
      const el = msgEls.nth(i);

      const prePlainText = await el.getAttribute(SELECTORS.MESSAGE_META_ATTR()) ?? "";
      const { date, senderName } = parsePrePlainText(prePlainText);

      const textEl = el.locator(SELECTORS.MESSAGE_TEXT()).first();
      const text = await textEl.textContent({ timeout: 1000 }).catch(() => "(media)");

      const outgoingSelector = SELECTORS.MESSAGE_OUTGOING();
      const outgoingDataAttr = SELECTORS.MESSAGE_OUTGOING_DATA_ATTR();
      const outgoingPrefix = SELECTORS.MESSAGE_OUTGOING_DATA_PREFIX();
      const isFromMe = await el.evaluate((node, { sel, attr, prefix }) => {
        if (node.closest(sel)) return true;
        const dataEl = node.closest(`[${attr}]`);
        return dataEl?.getAttribute(attr)?.startsWith(prefix) ?? false;
      }, { sel: outgoingSelector, attr: outgoingDataAttr, prefix: outgoingPrefix });

      messages.push({
        id: String(i - startIndex),
        text: (text ?? "(media)").trim(),
        date,
        senderName: senderName || (isFromMe ? "Me" : "Them"),
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
