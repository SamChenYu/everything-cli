import { chromium, type BrowserContext, type Page } from "playwright";
import * as path from "path";
import * as fs from "fs";
import * as dotenv from "dotenv";

export interface Chat {
  id: string;
  title: string;
  lastMessage: string;
  hasUnread: boolean;
}

export interface Message {
  id: string;
  text: string;
  date: Date;
  senderName: string;
  isFromMe: boolean;
  quotedText?: string;
}

const SESSION_DIR = path.join(process.cwd(), ".whatsapp-chrome-data");
const DIV_SELECTORS_PATH = path.join(process.cwd(), ".div-selectors");

const TIMEOUTS = {
  CHAT_LIST_INITIAL: 15_000,
  QR_CODE_APPEAR: 15_000,
  QR_LOGIN_COMPLETE: 120_000,
  CHAT_LIST_LOAD: 30_000,
  CHAT_PANEL_REFRESH: 10_000,
  MESSAGE_LOAD: 15_000,
  TEXT_CONTENT: 1_000,
  POST_TYPE_SETTLE: 300,
} as const;

const TYPE_DELAY_MS = 30;

const REQUIRED_ENV_KEYS = [
  "WA_CHAT_LIST_SELECTOR",
  "WA_CHAT_ROW_SELECTOR",
  "WA_CHAT_UNREAD_BADGE_SELECTOR",
  "WA_MESSAGE_WRAPPER_SELECTOR",
  "WA_MESSAGE_META_SELECTOR",
  "WA_MESSAGE_META_ATTR",
  "WA_MESSAGE_TEXT_SELECTOR",
  "WA_MESSAGE_OUTGOING_INDICATOR",
  "WA_QR_CODE_SELECTOR",
  "WA_INPUT_BOX_SELECTOR",
  "WA_SEND_BUTTON_SELECTOR",
] as const;

function loadSelectors() {
  if (!fs.existsSync(DIV_SELECTORS_PATH)) {
    console.error("Missing .div-selectors file in project root.");
    console.error(
      "This file holds the WhatsApp Web DOM selectors used by the CLI.",
    );
    console.error(
      "Run `npm run update-selectors` to regenerate it from a probe chat.",
    );
    process.exit(1);
  }

  const parsed = dotenv.parse(fs.readFileSync(DIV_SELECTORS_PATH));
  for (const [key, value] of Object.entries(parsed)) {
    if (process.env[key] === undefined) {
      process.env[key] = value;
    }
  }

  const missing = REQUIRED_ENV_KEYS.filter((key) => !process.env[key]);
  if (missing.length > 0) {
    console.error(
      "Missing required WhatsApp selector variables in .div-selectors:",
    );
    for (const key of missing) {
      console.error(`  - ${key}`);
    }
    process.exit(1);
  }

  return {
    CHAT_LIST: process.env.WA_CHAT_LIST_SELECTOR!,
    CHAT_ROW: process.env.WA_CHAT_ROW_SELECTOR!,
    CHAT_UNREAD_BADGE: process.env.WA_CHAT_UNREAD_BADGE_SELECTOR!,
    MESSAGE_WRAPPER: process.env.WA_MESSAGE_WRAPPER_SELECTOR!,
    MESSAGE_META: process.env.WA_MESSAGE_META_SELECTOR!,
    MESSAGE_META_ATTR: process.env.WA_MESSAGE_META_ATTR!,
    MESSAGE_TEXT: process.env.WA_MESSAGE_TEXT_SELECTOR!,
    OUTGOING_INDICATOR: process.env.WA_MESSAGE_OUTGOING_INDICATOR!,
    QR_CODE: process.env.WA_QR_CODE_SELECTOR!,
    INPUT_BOX: process.env.WA_INPUT_BOX_SELECTOR!,
    SEND_BUTTON: process.env.WA_SEND_BUTTON_SELECTOR!,
  };
}

const SELECTORS = loadSelectors();

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
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private headless: boolean;

  constructor(options?: { headless?: boolean }) {
    this.headless = options?.headless ?? true;
  }

  async launch(): Promise<void> {
    this.context = await chromium.launchPersistentContext(SESSION_DIR, {
      headless: this.headless,
      args: [
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
      ],
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      viewport: { width: 1280, height: 720 },
      locale: 'en-GB',
      timezoneId: 'Europe/London',
    });

    this.page = this.context.pages()[0] ?? await this.context.newPage();

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

    const chatListLocator = this.page.locator(SELECTORS.CHAT_LIST);
    const qrLocator = this.page.locator(SELECTORS.QR_CODE);

    // First, give the chat list a reasonably long time to appear (already logged-in case)
    const loggedIn = await chatListLocator
      .waitFor({ timeout: TIMEOUTS.CHAT_LIST_INITIAL })
      .then(() => true)
      .catch(() => false);

    if (loggedIn) {
      return;
    }

    // If chat list didn't appear, only treat this as "QR required" if the QR/login UI is visible
    const qrVisible = await qrLocator
      .waitFor({ timeout: TIMEOUTS.QR_CODE_APPEAR })
      .then(() => true)
      .catch(() => false);

    if (qrVisible) {
      // Not logged in — QR code scan required
      onQRRequired();
    }

    await chatListLocator.waitFor({ timeout: TIMEOUTS.QR_LOGIN_COMPLETE });
  }

  async getRecentChats(limit: number = 5): Promise<Chat[]> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    await this.page.locator(SELECTORS.CHAT_LIST).waitFor({ timeout: TIMEOUTS.CHAT_LIST_LOAD });

    const chatItems = await this.page.locator(`${SELECTORS.CHAT_LIST} > ${SELECTORS.CHAT_ROW}`).all();
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

      const hasUnread = (await item.locator(SELECTORS.CHAT_UNREAD_BADGE).count()) > 0;

      chats.push({
        id: String(i),
        title: title.trim(),
        lastMessage: lastMessage.trim(),
        hasUnread,
      });
    }

    return chats;
  }

  async openChat(chatTitle: string): Promise<void> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    const wrapperLocator = this.page.locator(SELECTORS.MESSAGE_WRAPPER);
    const hadMessages = (await wrapperLocator.count()) > 0;

    let oldFirstId: string | null = null;
    if (hadMessages) {
      oldFirstId = await wrapperLocator
        .first()
        .getAttribute("data-id")
        .catch(() => null);
    }

    const chatRows = await this.page.locator(`${SELECTORS.CHAT_LIST} > ${SELECTORS.CHAT_ROW}`).all();
    let item = null;
    for (const row of chatRows) {
      const title = await row.locator("span[title]").first().getAttribute("title").catch(() => null);
      if (title?.trim() === chatTitle) {
        item = row;
        break;
      }
    }

    if (!item) {
      throw new Error(`Chat "${chatTitle}" not found`);
    }

    await item.click();

    if (hadMessages && oldFirstId) {
      const sel = SELECTORS.MESSAGE_WRAPPER;
      await this.page.waitForFunction(
        ({ sel, oldId }) => {
          const el = document.querySelector(sel);
          return !el || el.getAttribute("data-id") !== oldId;
        },
        { sel, oldId: oldFirstId },
        { timeout: TIMEOUTS.CHAT_PANEL_REFRESH },
      ).catch(() => {});
    }

    await wrapperLocator.first().waitFor({ timeout: TIMEOUTS.MESSAGE_LOAD });
  }

  async getMessages(limit: number = 10): Promise<Message[]> {
    if (limit <= 0) {
      return [];
    }
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    await this.page.locator(SELECTORS.MESSAGE_WRAPPER).first().waitFor({ timeout: TIMEOUTS.MESSAGE_LOAD });

    const wrapperEls = this.page.locator(SELECTORS.MESSAGE_WRAPPER);
    const messages: Message[] = [];

    const totalCount = await wrapperEls.count();
    const startIndex = Math.max(0, totalCount - limit);

    for (let i = startIndex; i < totalCount; i++) {
      const wrapper = wrapperEls.nth(i);

      const isFromMe =
        (await wrapper.locator(SELECTORS.OUTGOING_INDICATOR).count()) > 0;

      const metaEl = wrapper.locator(SELECTORS.MESSAGE_META).first();
      const hasMeta = (await metaEl.count()) > 0;

      let date = new Date();
      let senderName = "";

      if (hasMeta) {
        const prePlainText = await metaEl.getAttribute(SELECTORS.MESSAGE_META_ATTR) ?? "";
        const parsed = parsePrePlainText(prePlainText);
        date = parsed.date;
        senderName = parsed.senderName;
      }

      const allTextEls = wrapper.locator(SELECTORS.MESSAGE_TEXT);
      const textCount = await allTextEls.count();

      let quotedText: string | undefined;
      if (textCount > 1) {
        quotedText = await allTextEls.first()
          .textContent({ timeout: TIMEOUTS.TEXT_CONTENT })
          .then((t) => t?.trim() || undefined)
          .catch(() => undefined);
      }

      const textEl = allTextEls.last();
      const text = await textEl.textContent({ timeout: TIMEOUTS.TEXT_CONTENT }).catch(() => null);

      const mediaLabel = text === null
        ? await wrapper.evaluate((node) => {
            const labels = Array.from(node.querySelectorAll("[aria-label]"))
              .map((e) => (e.getAttribute("aria-label") ?? "").toLowerCase());
            if (labels.some((l) => l.includes("picture") || l.includes("photo") || l.includes("image"))) return "<image>";
            if (labels.some((l) => l.includes("video"))) return "<video>";
            if (labels.some((l) => l.includes("audio") || l.includes("voice") || l.includes("ptt"))) return "<audio>";
            if (labels.some((l) => l.includes("gif"))) return "<gif>";
            if (labels.some((l) => l.includes("sticker"))) return "<sticker>";
            if (labels.some((l) => l.includes("document"))) return "<document>";
            return "<media>";
          })
        : null;

      messages.push({
        id: String(i - startIndex),
        text: (text ?? mediaLabel ?? "<media>").trim(),
        date,
        senderName: senderName || (isFromMe ? "Me" : "Them"),
        isFromMe,
        ...(quotedText ? { quotedText } : {}),
      });
    }

    return messages;
  }

  async sendMessage(text: string): Promise<void> {
    if (!this.page) {
      throw new Error("Browser not launched");
    }

    const inputBox = this.page.locator(SELECTORS.INPUT_BOX);
    await inputBox.click();
    await inputBox.pressSequentially(text, { delay: TYPE_DELAY_MS });

    await this.page.waitForTimeout(TIMEOUTS.POST_TYPE_SETTLE);

    const sendBtn = this.page.locator(SELECTORS.SEND_BUTTON);
    if (await sendBtn.isVisible().catch(() => false)) {
      await sendBtn.click();
    } else {
      await this.page.keyboard.press("Enter");
    }

    const postSendSettleMs = text.length * TYPE_DELAY_MS + 200;
    await this.page.waitForTimeout(postSendSettleMs);
  }

  async close(): Promise<void> {
    if (this.context) {
      await this.context.close();
      this.context = null;
      this.page = null;
    }
  }
}
