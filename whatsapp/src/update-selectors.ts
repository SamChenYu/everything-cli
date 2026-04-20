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
const ENV_SAMPLE_PATH = path.join(process.cwd(), ".env.sample");

const FALLBACK_UNREAD_BADGE = 'span[aria-label*="unread message"]';
const FALLBACK_QR = '[data-testid="qrcode"]';

function normalizeChatRowSelector(chatListSel: string, rowSel: string): string {
  const prefix = chatListSel.trim() + " > ";
  return rowSel.startsWith(prefix) ? rowSel.slice(prefix.length) : rowSel;
}

function patchEnvSample(updates: Record<string, string>): void {
  let text = fs.readFileSync(ENV_SAMPLE_PATH, "utf8");
  for (const [key, value] of Object.entries(updates)) {
    const re = new RegExp(
      "^(" + key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")=(.*)$",
      "m",
    );
    if (!re.test(text)) {
      throw new Error(`Key ${key} not found in .env.sample`);
    }
    text = text.replace(re, `$1=${value}`);
  }
  fs.writeFileSync(ENV_SAMPLE_PATH, text, "utf8");
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
  dataIdSample: string;
  messageTextSelector: string;
  metaSelector: string;
  metaAttr: string;
};

function longestCommonOutgoingPrefix(ids: string[]): string {
  if (ids.length === 0) return "true_";
  let p = ids[0] ?? "";
  for (const s of ids) {
    while (p.length > 0 && !s.startsWith(p)) {
      p = p.slice(0, -1);
    }
  }
  const u = p.lastIndexOf("_");
  if (u >= 0) return p.slice(0, u + 1);
  return p.length > 0 ? p : "true_";
}

async function findAlternateIdPrefixInMain(
  page: Page,
  tag: string,
  outgoingPrefix: string,
): Promise<string> {
  return await page.evaluate(
    ({ tag: t, outgoingPrefix: o }) => {
      const main = document.querySelector("#main");
      if (!main) return o === "true_" ? "false_" : "true_";
      const els = main.querySelectorAll(`${t}[data-id]`);
      for (const e of els) {
        const id = e.getAttribute("data-id") ?? "";
        if (id.length < 2 || id.startsWith(o)) continue;
        if (/^(true_|false_)/.test(id)) {
          return id.startsWith("true_") ? "true_" : "false_";
        }
        const idx = id.indexOf("_");
        if (idx > 0) return id.slice(0, idx + 1);
      }
      return o === "true_" ? "false_" : "true_";
    },
    { tag, outgoingPrefix },
  );
}

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

    const dataIdChain: Element[] = [];
    let cur: Element | null = el;
    while (cur && cur !== document.body) {
      if (cur.hasAttribute("data-id")) {
        dataIdChain.push(cur);
      }
      cur = cur.parentElement;
    }

    const isLikely = (id: string): boolean => {
      if (!id || id.length < 4) return false;
      if (/^(true_|false_)/.test(id)) return true;
      if (/@(?:c|g)\.us\b/.test(id)) return true;
      if (/@s\.whatsapp\.net\b/.test(id)) return true;
      if (id.includes("_") && id.length >= 12) return true;
      return false;
    };

    let wrapper: Element | null = null;
    for (const node of dataIdChain) {
      const id = node.getAttribute("data-id") ?? "";
      if (isLikely(id)) {
        wrapper = node;
        break;
      }
    }
    if (!wrapper && dataIdChain.length > 0) {
      wrapper = dataIdChain[0] ?? null;
    }
    if (!wrapper) {
      const main = el.closest("#main");
      if (main) {
        const candidates = Array.from(main.querySelectorAll("[data-id]")).filter(
          (node) => node.contains(el),
        );
        candidates.sort((a, b) => {
          const da = depthIn(main, a);
          const db = depthIn(main, b);
          return db - da;
        });
        for (const node of candidates) {
          const id = node.getAttribute("data-id") ?? "";
          if (isLikely(id) || id.length >= 8) {
            wrapper = node;
            break;
          }
        }
        if (!wrapper && candidates.length > 0) {
          wrapper = candidates[0] ?? null;
        }
      }
    }
    const depthIn = (root: Element, node: Element): number => {
      let d = 0;
      let x: Element | null = node;
      while (x && x !== root) {
        d++;
        x = x.parentElement;
      }
      return x === root ? d : -1;
    };
    if (!wrapper) {
      const ancestorChain: { tag: string; attrs: Record<string, string> }[] = [];
      let n: Element | null = el;
      for (let i = 0; i < 12 && n; i++, n = n.parentElement) {
        const a: Record<string, string> = {};
        for (const at of Array.from(n.attributes)) a[at.name] = at.value;
        ancestorChain.push({ tag: n.tagName.toLowerCase(), attrs: a });
      }
      const hint =
        dataIdChain.length === 0
          ? "No [data-id] found anywhere around the matched text."
          : `Found data-id ancestor(s), first id: ${(dataIdChain[0]?.getAttribute("data-id") ?? "").slice(0, 120)}`;
      throw Object.assign(
        new Error(`Could not find a message wrapper. ${hint}`),
        { __debugAncestors: ancestorChain },
      );
    }

    const dataId = wrapper.getAttribute("data-id") ?? "";

    const metaSelector = "[data-pre-plain-text]";
    const metaAttr = "data-pre-plain-text";

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
      dataIdSample: dataId,
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
  return await page.evaluate(() => {
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

    let inputSelector = 'div[role="textbox"][data-lexical-editor="true"]';
    if (!box.hasAttribute("data-lexical-editor")) {
      inputSelector = 'div[role="textbox"][contenteditable="true"]';
    } else {
      const ph = box.getAttribute("aria-placeholder");
      if (ph) {
        inputSelector = `div[role="textbox"][data-lexical-editor="true"][aria-placeholder="${ph.replace(/"/g, '\\"')}"]`;
      }
    }

    const footer = box.closest('footer') ?? box.parentElement ?? document.body;
    const buttons = Array.from(
      footer.querySelectorAll('button, [role="button"]'),
    ) as HTMLElement[];

    let sendEl: HTMLElement | null = null;
    for (const b of buttons) {
      const label = (b.getAttribute("aria-label") ?? "").toLowerCase();
      if (label.includes("send") || label.includes("enviar")) {
        sendEl = b;
        break;
      }
    }
    if (!sendEl && buttons.length > 0) {
      sendEl = buttons[buttons.length - 1] ?? null;
    }

    let sendSelector = '[aria-label="Send"]';
    if (sendEl) {
      const al = sendEl.getAttribute("aria-label");
      if (al) {
        sendSelector = `[aria-label="${al.replace(/"/g, '\\"')}"]`;
      } else {
        const tid = sendEl.getAttribute("data-testid");
        if (tid) sendSelector = `[data-testid="${tid}"]`;
      }
    }

    return { inputSelector, sendSelector };
  });
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
    if (p.wrapperTag !== w0.wrapperTag || p.messageTextSelector !== w0.messageTextSelector) {
      throw new Error(
        "Probe messages produced inconsistent DOM patterns — check that all three lines are plain outgoing text in the same thread.",
      );
    }
  }

  const tag = w0.wrapperTag;
  const ids = probes.map((p) => p.dataIdSample);
  const allTrue = ids.every((i) => i.startsWith("true_"));
  const allFalse = ids.every((i) => i.startsWith("false_"));
  let outP =
    allTrue ? "true_" : allFalse ? "false_" : longestCommonOutgoingPrefix(ids);
  if (!outP || outP.length < 2) {
    outP = ids[0]?.match(/^(true_|false_)/)?.[1] ?? "true_";
  }

  let inP = await findAlternateIdPrefixInMain(page, tag, outP);
  if (inP === outP) {
    inP = outP === "true_" ? "false_" : "true_";
  }

  const messageWrapper = `${tag}[data-id^="${outP}"], ${tag}[data-id^="${inP}"]`;

  const composer = await probeComposer(page);

  return {
    WA_MESSAGE_WRAPPER_SELECTOR: messageWrapper,
    WA_MESSAGE_META_SELECTOR: w0.metaSelector,
    WA_MESSAGE_META_ATTR: w0.metaAttr,
    WA_MESSAGE_TEXT_SELECTOR: w0.messageTextSelector,
    WA_MESSAGE_OUTGOING_PREFIX: allTrue ? "true_" : allFalse ? "false_" : outP,
    WA_INPUT_BOX_SELECTOR: composer.inputSelector,
    WA_SEND_BUTTON_SELECTOR: composer.sendSelector,
    WA_CHAT_UNREAD_BADGE_SELECTOR: FALLBACK_UNREAD_BADGE,
    WA_QR_CODE_SELECTOR: FALLBACK_QR,
  };
}

async function main(): Promise<void> {
  if (!fs.existsSync(ENV_SAMPLE_PATH)) {
    console.error("Missing .env.sample in project root.");
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

    patchEnvSample(partial);

    console.log(
      [
        "",
        "Updated .env.sample from fixture content + DOM analysis.",
        "Unread badge and QR selectors were not probed (defaults kept).",
        "Copy .env.sample → .env if you use a local env file.",
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
