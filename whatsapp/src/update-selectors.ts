import { chromium, type Locator, type Page } from "playwright";
import * as fs from "fs";
import * as path from "path";
import * as readline from "readline/promises";
import { stdin as input, stdout as output } from "node:process";

/**
 * Fixture: create a group (or chat) with this exact title on your phone,
 * send only these three messages from your account (outgoing), in order.
 * They are ASCII and easy to copy-paste.
 */
const PROBE_CHAT_TITLE = "WA-SEL-FIX-7c2a9e1d";

const PROBE_MESSAGES = [
  "WA_SEL_PROBE_LINE_01_V1",
  "WA_SEL_PROBE_LINE_02_V1",
  "WA_SEL_PROBE_LINE_03_V1",
] as const;

const SESSION_DIR = path.join(process.cwd(), ".whatsapp-chrome-data");
const DIV_SELECTORS_PATH = path.join(process.cwd(), ".div-selectors");

const FALLBACK_UNREAD_BADGE = 'span[aria-label*="unread message"]';
const FALLBACK_QR = '[data-testid="qrcode"]';

function normalizeChatRowSelector(chatListSel: string, rowSel: string): string {
  const prefix = chatListSel.trim() + " > ";
  return rowSel.startsWith(prefix) ? rowSel.slice(prefix.length) : rowSel;
}

/**
 * dotenv treats `#` in an unquoted value as the start of an inline comment, so
 * a CSS id selector like `#main …` would parse as the empty string. Wrap any
 * value that contains `#`, leading/trailing whitespace, or no characters at
 * all in double quotes (escaping any embedded `"`) to keep dotenv happy.
 */
function formatEnvValue(value: string): string {
  const needsQuoting = /^$|^\s|\s$|#/.test(value);
  if (!needsQuoting) return value;
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function patchDivSelectors(updates: Record<string, string>): void {
  let text = fs.readFileSync(DIV_SELECTORS_PATH, "utf8");
  for (const [key, value] of Object.entries(updates)) {
    const re = new RegExp(
      "^(" + key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")=(.*)$",
      "m",
    );
    if (!re.test(text)) {
      throw new Error(`Key ${key} not found in .div-selectors`);
    }
    text = text.replace(re, `$1=${formatEnvValue(value)}`);
  }
  fs.writeFileSync(DIV_SELECTORS_PATH, text, "utf8");
}

function conversationScope(page: Page): Locator {
  const main = page.locator("#main");
  return main;
}

function messageLocator(scope: Locator, text: string): Locator {
  return scope.getByText(text, { exact: true });
}

type MessageDomProbe = {
  wrapperTag: string;
  hasMessageOut: boolean;
  hasMessageIn: boolean;
  hasMetaAttr: boolean;
  messageTextSelector: string;
  metaSelector: string;
  metaAttr: string;
};

/**
 * Walks up from the matched text node to find the closest `[data-id]` ancestor
 * that actually wraps a chat message — i.e., one that has either
 * `.message-out` (sent by you) or `.message-in` (sent by someone else)
 * somewhere inside it. This deliberately ignores the `data-id` *value*:
 * since 2024-ish WhatsApp Web uses raw hex ids (e.g. `3EB0…`) with no
 * `true_`/`false_` direction prefix, so trying to detect direction from
 * the id is unreliable. The `message-out` / `message-in` class names have
 * been stable for years and are the source of truth for direction.
 */
async function probeMessageDom(
  page: Page,
  scope: Locator,
  text: string,
): Promise<MessageDomProbe> {
  const loc = messageLocator(scope, text);
  const count = await loc.count();
  if (count === 0) {
    throw new Error(
      `Could not find message text "${text}" in #main. Scroll until all three probe lines are visible.`,
    );
  }
  const target = count > 1 ? loc.last() : loc.first();
  await target.waitFor({ state: "visible", timeout: 25_000 });

  return await target.evaluate((start: Node) => {
    const el =
      start.nodeType === Node.ELEMENT_NODE
        ? (start as Element)
        : start.parentElement;
    if (!el) {
      throw new Error("No element for message probe");
    }

    let wrapper: Element | null = null;
    let cur: Element | null = el;
    while (cur && cur !== document.body) {
      if (
        cur.hasAttribute("data-id") &&
        cur.querySelector("div.message-out, div.message-in")
      ) {
        wrapper = cur;
        break;
      }
      cur = cur.parentElement;
    }

    if (!wrapper) {
      const ancestorChain: { tag: string; attrs: Record<string, string> }[] =
        [];
      let n: Element | null = el;
      for (let i = 0; i < 12 && n; i++, n = n.parentElement) {
        const a: Record<string, string> = {};
        for (const at of Array.from(n.attributes)) a[at.name] = at.value;
        ancestorChain.push({ tag: n.tagName.toLowerCase(), attrs: a });
      }
      throw Object.assign(
        new Error(
          "Could not find a message wrapper (no [data-id] ancestor with " +
            ".message-in/.message-out descendant). Has WhatsApp changed " +
            "the wrapper structure?",
        ),
        { __debugAncestors: ancestorChain },
      );
    }

    const hasMessageOut = wrapper.querySelector("div.message-out") !== null;
    const hasMessageIn = wrapper.querySelector("div.message-in") !== null;

    const metaSelector = "[data-pre-plain-text]";
    const metaAttr = "data-pre-plain-text";
    const hasMetaAttr = wrapper.querySelector(metaSelector) !== null;

    const textEl =
      wrapper.querySelector("[data-testid='selectable-text']") ??
      wrapper.querySelector("span[dir='auto']");
    let messageTextSelector = "span[data-testid='selectable-text']";
    if (textEl) {
      const tid = textEl.getAttribute("data-testid");
      if (tid) {
        messageTextSelector = `[data-testid="${tid}"]`;
      } else if (textEl instanceof HTMLElement && textEl.tagName === "SPAN") {
        messageTextSelector = "span[dir='auto']";
      }
    }

    return {
      wrapperTag: wrapper.tagName.toLowerCase(),
      hasMessageOut,
      hasMessageIn,
      hasMetaAttr,
      messageTextSelector,
      metaSelector,
      metaAttr,
    };
  });
}

async function probeComposer(page: Page): Promise<{
  inputSelector: string;
  sendSelector: string;
}> {
  const inputSelector = await page.evaluate(() => {
    const box =
      document.querySelector(
        'div[role="textbox"][data-lexical-editor="true"]',
      ) ??
      document.querySelector('div[role="textbox"][contenteditable="true"]');
    if (!box) {
      throw new Error(
        "Could not find message input (Lexical / contenteditable textbox).",
      );
    }
    if (!box.hasAttribute("data-lexical-editor")) {
      return 'div[role="textbox"][contenteditable="true"]';
    }
    const ph = box.getAttribute("aria-placeholder");
    return ph
      ? `div[role="textbox"][data-lexical-editor="true"][aria-placeholder="${ph.replace(/"/g, '\\"')}"]`
      : 'div[role="textbox"][data-lexical-editor="true"]';
  });

  // The Send button only exists while the composer has text; an empty composer
  // shows the Voice-message button in the same slot, which is what the script
  // would otherwise mistakenly grab. Type a single throwaway char, probe, then
  // clear it.
  const inputBox = page.locator(inputSelector);
  await inputBox.click();
  await inputBox.pressSequentially("x", { delay: 30 });
  await page.waitForTimeout(300);

  const sendSelector = await page.evaluate(() => {
    const candidates = Array.from(
      document.querySelectorAll('button, [role="button"]'),
    ) as HTMLElement[];
    for (const b of candidates) {
      const raw = b.getAttribute("aria-label") ?? "";
      const label = raw.toLowerCase();
      // Match common aria-labels across locales: en "Send", es "Enviar",
      // pt "Enviar", de "Senden", fr "Envoyer", etc. Be strict to avoid
      // catching things like "Send a message …" placeholders.
      if (
        label === "send" ||
        label === "enviar" ||
        label === "senden" ||
        label === "envoyer"
      ) {
        return `[aria-label="${raw.replace(/"/g, '\\"')}"]`;
      }
    }
    return '[aria-label="Send"]';
  });

  await inputBox.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.press("Backspace");

  return { inputSelector, sendSelector };
}

type SidebarProbe = {
  chatListSelector: string;
  chatRowSelector: string;
};

async function probeSidebarForTitle(
  page: Page,
  title: string,
): Promise<SidebarProbe> {
  const titleLoc = page.locator(`span[title="${title}"]`).first();
  await titleLoc.waitFor({ state: "visible", timeout: 30_000 });

  return await titleLoc.evaluate((span, probeTitle) => {
    const want = String(probeTitle);
    if ((span.getAttribute("title") ?? "").trim() !== want) {
      throw new Error("Title span mismatch");
    }

    let row: Element | null = span;
    while (row && row !== document.body) {
      if (row.getAttribute("role") === "row") break;
      row = row.parentElement;
    }
    if (!row || row.getAttribute("role") !== "row") {
      throw new Error(
        'Could not find chat row (ancestor with role="row") for fixture title.',
      );
    }

    let list: Element | null = row.closest('[aria-label="Chat list"]');
    if (!list) {
      let cur: Element | null = row;
      for (let i = 0; i < 30 && cur; i++, cur = cur.parentElement) {
        const al = (cur.getAttribute("aria-label") ?? "").toLowerCase();
        if (al.includes("chat") && al.includes("list")) {
          list = cur;
          break;
        }
      }
    }
    if (!list) list = row.parentElement;
    if (!list) {
      throw new Error("Could not resolve chat list container from fixture row.");
    }

    const listAria = list.getAttribute("aria-label");
    const chatListSelector = listAria
      ? `[aria-label="${listAria.replace(/"/g, '\\"')}"]`
      : '[aria-label="Chat list"]';

    let rowDirectChild: Element = row;
    while (rowDirectChild.parentElement && rowDirectChild.parentElement !== list) {
      rowDirectChild = rowDirectChild.parentElement;
    }
    if (rowDirectChild.parentElement !== list) {
      throw new Error("Row is not under detected chat list node.");
    }

    const candidateSelectors: string[] = [];
    const rowRole = rowDirectChild.getAttribute("role");
    const rowTag = rowDirectChild.tagName.toLowerCase();
    if (rowRole) candidateSelectors.push(`${rowTag}[role="${rowRole}"]`);
    const tabIndex = rowDirectChild.getAttribute("tabindex");
    if (tabIndex !== null && rowRole) {
      candidateSelectors.push(`${rowTag}[role="${rowRole}"][tabindex="${tabIndex}"]`);
    }
    const tid = rowDirectChild.getAttribute("data-testid");
    if (tid) candidateSelectors.push(`${rowTag}[data-testid="${tid}"]`);
    candidateSelectors.push(rowTag);

    const listEl = list as Element;
    let chatRowSelector: string | null = null;
    let bestCount = 0;
    for (const sel of candidateSelectors) {
      const matches = listEl.querySelectorAll(`:scope > ${sel}`);
      if (matches.length > bestCount) {
        bestCount = matches.length;
        chatRowSelector = sel;
        if (matches.length >= 2 && rowRole) break;
      }
    }
    if (!chatRowSelector) {
      chatRowSelector = `${rowTag}[role="row"]`;
    }

    return { chatListSelector, chatRowSelector };
  }, title);
}

async function analyzeConversation(page: Page): Promise<Record<string, string>> {
  const scope = conversationScope(page);
  if ((await scope.count()) === 0) {
    throw new Error('Conversation panel #main not found. Is WhatsApp Web loaded?');
  }

  const probes: MessageDomProbe[] = [];
  for (const line of PROBE_MESSAGES) {
    probes.push(await probeMessageDom(page, scope, line));
  }

  const w0 = probes[0]!;
  for (const p of probes) {
    if (
      p.wrapperTag !== w0.wrapperTag ||
      p.messageTextSelector !== w0.messageTextSelector
    ) {
      throw new Error(
        "Probe messages produced inconsistent DOM patterns — check that all three lines are plain outgoing text in the same thread.",
      );
    }
  }

  if (!probes.every((p) => p.hasMessageOut)) {
    throw new Error(
      "Probe messages don't all carry the `.message-out` class. Make sure " +
        `the three "${PROBE_CHAT_TITLE}" probe lines were sent BY YOU (not ` +
        "received from someone else).",
    );
  }

  if (!probes.every((p) => p.hasMetaAttr)) {
    throw new Error(
      "Probe messages are missing `[data-pre-plain-text]`. WhatsApp may have " +
        "renamed this attribute — update WA_MESSAGE_META_SELECTOR / _ATTR " +
        "manually in .div-selectors.",
    );
  }

  const tag = w0.wrapperTag;
  // `:has(...)` filters out non-message rows under #main (encryption notice,
  // group-profile card, "Today" date separator, etc. — they have data-id but
  // no .message-in/.message-out descendant).
  const messageWrapper = `#main ${tag}[data-id]:has(div.message-in, div.message-out)`;

  const composer = await probeComposer(page);

  return {
    WA_MESSAGE_WRAPPER_SELECTOR: messageWrapper,
    WA_MESSAGE_META_SELECTOR: w0.metaSelector,
    WA_MESSAGE_META_ATTR: w0.metaAttr,
    WA_MESSAGE_TEXT_SELECTOR: w0.messageTextSelector,
    WA_MESSAGE_OUTGOING_INDICATOR: "div.message-out",
    WA_INPUT_BOX_SELECTOR: composer.inputSelector,
    WA_SEND_BUTTON_SELECTOR: composer.sendSelector,
    WA_CHAT_UNREAD_BADGE_SELECTOR: FALLBACK_UNREAD_BADGE,
    WA_QR_CODE_SELECTOR: FALLBACK_QR,
  };
}

async function main(): Promise<void> {
  if (!fs.existsSync(DIV_SELECTORS_PATH)) {
    console.error("Missing .div-selectors in project root.");
    process.exit(1);
  }

  const rl = readline.createInterface({ input, output });

  console.log(
    [
      "WhatsApp selector calibration (fixture chat)",
      "--------------------------------------------",
      "",
      "1. On your phone, create a group or chat titled exactly:",
      `   ${PROBE_CHAT_TITLE}`,
      "",
      "2. Send only these three messages, from you, in order (copy-paste):",
      ...PROBE_MESSAGES.map((m) => `   • ${m}`),
      "",
      "3. A browser window will open. Log in if needed.",
      "",
    ].join("\n"),
  );

  const browser = await chromium.launchPersistentContext(SESSION_DIR, {
    headless: false,
    args: ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    viewport: { width: 1280, height: 720 },
    locale: "en-GB",
    timezoneId: "Europe/London",
  });

  const page = browser.pages()[0] ?? (await browser.newPage());
  await page.addInitScript({
    content:
      'Object.defineProperty(navigator,"webdriver",{get:function(){return false;}});' +
      'globalThis.__name=function(f){return f;};',
  });

  await page.goto("https://web.whatsapp.com", { waitUntil: "domcontentloaded" });

  try {
    await rl.question(
      [
        "",
        `Open the chat titled "${PROBE_CHAT_TITLE}" in the browser.`,
        "Scroll so all three probe messages are visible in the thread.",
        "",
        "Press Enter here when ready… ",
      ].join("\n"),
    );

    let partial: Record<string, string>;
    try {
      partial = await analyzeConversation(page);
    } catch (err) {
      const dump = await page
        .evaluate((probes) => {
          const escape = (s: string) => {
            return s.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c] ?? c));
          }
          const out: string[] = [];
          const main = document.querySelector("#main");
          out.push(`#main found: ${main ? "yes" : "no"}`);
          for (const p of probes) {
            out.push(`\n--- probe: ${p}`);
            const walker = document.createTreeWalker(
              main ?? document.body,
              NodeFilter.SHOW_TEXT,
            );
            let hit: Element | null = null;
            for (let n = walker.nextNode(); n; n = walker.nextNode()) {
              if (n.textContent && n.textContent.includes(p)) {
                hit = n.parentElement;
                break;
              }
            }
            if (!hit) {
              out.push("  not found in DOM");
              continue;
            }
            let cur: Element | null = hit;
            for (let i = 0; i < 10 && cur; i++, cur = cur.parentElement) {
              const attrs = Array.from(cur.attributes)
                .map((a) => `${a.name}="${escape(a.value).slice(0, 80)}"`)
                .join(" ");
              out.push(`  [${i}] <${cur.tagName.toLowerCase()} ${attrs}>`);
            }
          }
          return out.join("\n");
        }, PROBE_MESSAGES as unknown as string[])
        .catch(() => "(snapshot failed)");
      const dumpPath = path.join(process.cwd(), "wa-selector-debug.txt");
      fs.writeFileSync(dumpPath, dump, "utf8");
      console.error(`\nProbe failed. Wrote DOM snapshot to: ${dumpPath}\n`);
      throw err;
    }

    await rl.question(
      [
        "",
        `Make sure the chat row "${PROBE_CHAT_TITLE}" is visible in the left sidebar`,
        "(scroll the chat list if needed). Then press Enter… ",
      ].join("\n"),
    );

    const side = await probeSidebarForTitle(page, PROBE_CHAT_TITLE);
    partial.WA_CHAT_LIST_SELECTOR = side.chatListSelector;
    partial.WA_CHAT_ROW_SELECTOR = normalizeChatRowSelector(
      side.chatListSelector,
      side.chatRowSelector,
    );

    patchDivSelectors(partial);

    console.log(
      [
        "",
        "Updated .div-selectors from fixture content + DOM analysis.",
        "Unread badge and QR selectors were not probed (defaults kept).",
        "",
      ].join("\n"),
    );
  } finally {
    await browser.close();
    rl.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
