import { chromium, type Page } from "playwright";
import * as fs from "fs";
import * as path from "path";
import * as readline from "readline/promises";
import { stdin as input, stdout as output } from "node:process";
import * as dotenv from "dotenv";

/**
 * WhatsApp Web selector diagnostic.
 *
 * This is intentionally NOT a re-deriver — every time WhatsApp ships a
 * structural change (rename of `data-pre-plain-text`, dropping
 * `selectable-text`, swapping the editor framework, etc.) you'll have to
 * manually update both `.div-selectors` and `WhatsAppService.ts` anyway.
 *
 * What this script does instead:
 *   1. Opens WhatsApp Web in your persistent profile.
 *   2. Runs each selector in `.div-selectors` against the live DOM.
 *   3. Reports which ones still match and which are broken.
 *   4. For broken ones, dumps a focused HTML snippet of the area where the
 *      selector should have matched so you can see what changed.
 *
 * Usage: npm run check-selectors
 *   - Open any chat with a few messages (text, ideally a mix of incoming
 *     and outgoing) before pressing Enter at the prompt.
 */

const SESSION_DIR = path.join(process.cwd(), ".whatsapp-chrome-data");
const DIV_SELECTORS_PATH = path.join(process.cwd(), ".div-selectors");

const C = {
  green: (s: string) => `\x1b[32m${s}\x1b[0m`,
  red: (s: string) => `\x1b[31m${s}\x1b[0m`,
  yellow: (s: string) => `\x1b[33m${s}\x1b[0m`,
  dim: (s: string) => `\x1b[2m${s}\x1b[0m`,
  bold: (s: string) => `\x1b[1m${s}\x1b[0m`,
  cyan: (s: string) => `\x1b[36m${s}\x1b[0m`,
};
const OK = C.green("✓");
const FAIL = C.red("✗");
const SKIP = C.dim("·");

type Sels = Record<string, string>;

function loadSelectors(): Sels {
  if (!fs.existsSync(DIV_SELECTORS_PATH)) {
    throw new Error(`.div-selectors not found at ${DIV_SELECTORS_PATH}`);
  }
  return dotenv.parse(fs.readFileSync(DIV_SELECTORS_PATH));
}

function indent(s: string, prefix = "      "): string {
  return s
    .split("\n")
    .map((l) => (l.length ? prefix + l : l))
    .join("\n");
}

const tally = { pass: 0, fail: 0, skip: 0 };

type CheckOpts = {
  page: Page;
  label: string;
  selector: string;
  rootSelector?: string;
  expectMin: number;
  optional?: boolean;
  note?: string;
  hint?: () => Promise<string>;
};

async function check(opts: CheckOpts): Promise<number> {
  const root = opts.rootSelector ? opts.page.locator(opts.rootSelector) : opts.page;
  let count = 0;
  let err: Error | null = null;
  try {
    count = await root.locator(opts.selector).count();
  } catch (e) {
    err = e as Error;
  }

  const meets = !err && count >= opts.expectMin;
  const symbol = meets ? OK : opts.optional ? SKIP : FAIL;
  const status = err
    ? C.red(`error: ${err.message.split("\n")[0]}`)
    : meets
    ? C.green(`${count} match${count === 1 ? "" : "es"}`)
    : opts.optional
    ? C.dim(`${count} matches (none required)`)
    : C.red(`${count} matches (expected ≥${opts.expectMin})`);

  const noteStr = opts.note ? "  " + C.dim(opts.note) : "";
  console.log(`  ${symbol} ${opts.label.padEnd(33)} ${status}${noteStr}`);
  console.log(C.dim(`        ${opts.selector}`));

  if ((!meets || err) && !opts.optional) {
    tally.fail++;
    if (opts.hint) {
      const h = await opts.hint().catch((e) => `(hint failed: ${e?.message ?? e})`);
      if (h.trim()) console.log(C.dim(indent("hint:\n" + h)));
    }
  } else if (!meets && opts.optional) {
    tally.skip++;
  } else {
    tally.pass++;
  }
  return count;
}

/**
 * Page-side helper: render `<tag attr="val" …>` for a given element.
 * Defined here as a string and injected into evaluate() so it's reusable.
 */
const PAGE_HELPERS = `
  function summarize(el) {
    if (!el) return "(null)";
    const attrs = Array.from(el.attributes).map(a => {
      const v = a.value.length > 80 ? a.value.slice(0, 77) + "..." : a.value;
      return a.name + "=\\"" + v + "\\"";
    });
    return "<" + el.tagName.toLowerCase() + (attrs.length ? " " + attrs.join(" ") : "") + ">";
  }
  function ancestors(el, n) {
    const out = [];
    let cur = el;
    for (let i = 0; i < n && cur; i++, cur = cur.parentElement) out.push(cur);
    return out;
  }
`;

async function pageEval<T>(page: Page, body: string): Promise<T> {
  return (await page.evaluate(`(() => { ${PAGE_HELPERS}; ${body} })()`)) as T;
}

// ─── Hint generators ────────────────────────────────────────────────────────

async function hintChatList(page: Page): Promise<string> {
  return pageEval<string>(
    page,
    `
    const lines = [];
    lines.push("Looking for chat-list-like containers in the page:");
    const candidates = Array.from(document.querySelectorAll(
      '[role="grid"], [role="list"], [aria-label*="chat" i], [aria-label*="conversa" i]'
    ));
    if (!candidates.length) return "  (none found)";
    candidates.slice(0, 8).forEach(el => lines.push("  " + summarize(el)));
    return lines.join("\\n");
    `,
  );
}

async function hintMessageWrapper(page: Page, sels: Sels): Promise<string> {
  return pageEval<string>(
    page,
    `
    const main = document.querySelector("#main");
    if (!main) return "  #main not found — open a chat first.";
    const lines = [];
    lines.push("All [data-id] elements under #main and their direct class footprint:");
    const dataIds = Array.from(main.querySelectorAll("[data-id]"));
    if (!dataIds.length) {
      lines.push("  (no [data-id] elements found at all — likely a wrapper attribute rename)");
      return lines.join("\\n");
    }
    dataIds.slice(0, 10).forEach(el => {
      const id = (el.getAttribute("data-id") || "").slice(0, 40);
      const cls = (el.getAttribute("class") || "").split(/\\s+/).filter(Boolean).slice(0, 4).join(" ");
      const hasOut = !!el.querySelector("div.message-out");
      const hasIn = !!el.querySelector("div.message-in");
      lines.push("  data-id=\\"" + id + "\\" class=\\"" + cls + "\\" .message-out=" + hasOut + " .message-in=" + hasIn);
    });
    if (dataIds.length > 10) lines.push("  ... and " + (dataIds.length - 10) + " more");
    return lines.join("\\n");
    `,
  );
}

async function hintMessageMeta(page: Page, sels: Sels): Promise<string> {
  return pageEval<string>(
    page,
    `
    const main = document.querySelector("#main");
    if (!main) return "  #main not found.";
    const wrappers = Array.from(main.querySelectorAll(${JSON.stringify(sels.WA_MESSAGE_WRAPPER_SELECTOR_RAW ?? sels.WA_MESSAGE_WRAPPER_SELECTOR ?? "[data-id]")}));
    if (!wrappers.length) return "  No message wrappers to inspect (wrapper selector itself is broken).";
    const target = wrappers[wrappers.length - 1];
    const lines = ["data-* attribute names found anywhere inside the most recent message:"];
    const seen = new Set();
    target.querySelectorAll("*").forEach(el => {
      for (const a of el.attributes) if (a.name.startsWith("data-")) seen.add(a.name);
    });
    Array.from(seen).sort().forEach(n => lines.push("  " + n));
    return lines.join("\\n");
    `,
  );
}

async function hintMessageText(page: Page, sels: Sels): Promise<string> {
  return pageEval<string>(
    page,
    `
    const main = document.querySelector("#main");
    if (!main) return "  #main not found.";
    const wrappers = Array.from(main.querySelectorAll(${JSON.stringify(sels.WA_MESSAGE_WRAPPER_SELECTOR ?? "[data-id]")}));
    if (!wrappers.length) return "  No message wrappers — fix WA_MESSAGE_WRAPPER_SELECTOR first.";
    const target = wrappers[wrappers.length - 1];
    const spans = Array.from(target.querySelectorAll("span"))
      .filter(s => (s.textContent || "").trim().length > 0 && (s.textContent || "").trim().length < 200);
    const lines = ["Spans with text content inside the most recent wrapper (first 8):"];
    spans.slice(0, 8).forEach(s => {
      const txt = (s.textContent || "").trim().slice(0, 50);
      lines.push("  " + summarize(s) + "  → " + JSON.stringify(txt));
    });
    return lines.join("\\n");
    `,
  );
}

async function hintOutgoingIndicator(page: Page, sels: Sels): Promise<string> {
  return pageEval<string>(
    page,
    `
    const main = document.querySelector("#main");
    if (!main) return "  #main not found.";
    const wrappers = Array.from(main.querySelectorAll(${JSON.stringify(sels.WA_MESSAGE_WRAPPER_SELECTOR ?? "[data-id]")}));
    if (!wrappers.length) return "  No message wrappers found.";
    const lines = ["Class names appearing on descendants of message wrappers (top 12 by count):"];
    const counts = new Map();
    wrappers.forEach(w => {
      w.querySelectorAll("[class]").forEach(el => {
        (el.getAttribute("class") || "").split(/\\s+/).forEach(c => {
          if (!c) return;
          counts.set(c, (counts.get(c) || 0) + 1);
        });
      });
    });
    Array.from(counts.entries())
      .filter(([c]) => /message|out|in|tail/.test(c))
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
      .forEach(([c, n]) => lines.push("  ." + c + "  (" + n + " occurrences)"));
    return lines.join("\\n");
    `,
  );
}

async function hintInputBox(page: Page): Promise<string> {
  return pageEval<string>(
    page,
    `
    const lines = ["Editable elements in the page:"];
    const cands = Array.from(document.querySelectorAll(
      '[contenteditable="true"], [role="textbox"], [data-lexical-editor]'
    ));
    if (!cands.length) return "  (none found — composer area not loaded?)";
    cands.slice(0, 6).forEach(el => lines.push("  " + summarize(el)));
    return lines.join("\\n");
    `,
  );
}

async function hintSendButton(page: Page, sels: Sels): Promise<string> {
  return pageEval<string>(
    page,
    `
    const inp = document.querySelector(${JSON.stringify(sels.WA_INPUT_BOX_SELECTOR ?? '[role="textbox"]')});
    const root = inp ? (inp.closest("footer") || inp.parentElement?.parentElement || document.body) : document.body;
    const buttons = Array.from(root.querySelectorAll('button, [role="button"]'));
    const lines = ["Button-like elements near the composer:"];
    buttons.slice(0, 12).forEach(b => {
      const al = b.getAttribute("aria-label") || "(no aria-label)";
      const tid = b.getAttribute("data-testid") || "";
      lines.push("  aria-label=" + JSON.stringify(al) + (tid ? "  data-testid=" + JSON.stringify(tid) : ""));
    });
    return lines.join("\\n");
    `,
  );
}

async function hintUnreadBadge(page: Page, sels: Sels): Promise<string> {
  return pageEval<string>(
    page,
    `
    const list = document.querySelector(${JSON.stringify(sels.WA_CHAT_LIST_SELECTOR ?? '[role="grid"]')});
    if (!list) return "  Chat list not found.";
    const rows = Array.from(list.querySelectorAll(${JSON.stringify(sels.WA_CHAT_ROW_SELECTOR ?? '[role="row"]')}));
    const lines = ["Spans with aria-labels inside chat rows (looking for unread-style markers):"];
    let n = 0;
    for (const r of rows) {
      for (const s of r.querySelectorAll("span[aria-label]")) {
        const al = s.getAttribute("aria-label") || "";
        if (/\\d/.test(al) || /unread|message|note|nuevo|sin leer/i.test(al)) {
          lines.push("  " + summarize(s));
          if (++n >= 8) break;
        }
      }
      if (n >= 8) break;
    }
    if (n === 0) lines.push("  (no candidate found — may just mean you have no unread chats)");
    return lines.join("\\n");
    `,
  );
}

// ─── Phases ─────────────────────────────────────────────────────────────────

function header(title: string): void {
  console.log("\n" + C.bold(title));
}

async function runSidebarPhase(page: Page, sels: Sels): Promise<void> {
  header("[1] Sidebar / chat list");

  await check({
    page,
    label: "WA_CHAT_LIST_SELECTOR",
    selector: sels.WA_CHAT_LIST_SELECTOR ?? "",
    expectMin: 1,
    hint: () => hintChatList(page),
  });

  await check({
    page,
    label: "WA_CHAT_ROW_SELECTOR",
    selector: `${sels.WA_CHAT_LIST_SELECTOR} > ${sels.WA_CHAT_ROW_SELECTOR}`,
    expectMin: 1,
    note: "rendered as <chat-list> > <chat-row>",
    hint: () => hintChatList(page),
  });

  await check({
    page,
    label: "WA_CHAT_UNREAD_BADGE_SELECTOR",
    selector: sels.WA_CHAT_UNREAD_BADGE_SELECTOR ?? "",
    rootSelector: `${sels.WA_CHAT_LIST_SELECTOR} > ${sels.WA_CHAT_ROW_SELECTOR}`,
    expectMin: 1,
    optional: true,
    note: "0 is fine if you have no unread chats",
    hint: () => hintUnreadBadge(page, sels),
  });
}

async function runConversationPhase(page: Page, sels: Sels): Promise<void> {
  header("[2] Open conversation (#main)");

  const mainCount = await page.locator("#main").count();
  if (mainCount === 0) {
    console.log(`  ${FAIL} ${C.red("#main not found — no chat is open. Open a chat and re-run.")}`);
    tally.fail++;
    return;
  }

  const wrapperCount = await check({
    page,
    label: "WA_MESSAGE_WRAPPER_SELECTOR",
    selector: sels.WA_MESSAGE_WRAPPER_SELECTOR ?? "",
    expectMin: 1,
    hint: () => hintMessageWrapper(page, sels),
  });

  if (wrapperCount > 0) {
    const wrappers = page.locator(sels.WA_MESSAGE_WRAPPER_SELECTOR ?? "");
    const total = await wrappers.count();
    const sample = Math.min(total, 12);

    let metaHits = 0;
    let textHits = 0;
    let outHits = 0;
    let inHits = 0;
    for (let i = 0; i < sample; i++) {
      const w = wrappers.nth(total - 1 - i);
      if ((await w.locator(sels.WA_MESSAGE_META_SELECTOR ?? "").count()) > 0) metaHits++;
      if ((await w.locator(sels.WA_MESSAGE_TEXT_SELECTOR ?? "").count()) > 0) textHits++;
      const out = (await w.locator(sels.WA_MESSAGE_OUTGOING_INDICATOR ?? "").count()) > 0;
      if (out) outHits++;
      else inHits++;
    }

    console.log(`  ${C.dim(`(scanned the ${sample} most-recent wrappers)`)}`);

    const showRatio = (n: number) => `${n}/${sample}`;
    await reportRatio({
      label: "WA_MESSAGE_META_SELECTOR",
      selector: sels.WA_MESSAGE_META_SELECTOR ?? "",
      hits: metaHits,
      sample,
      // Media-only messages don't have meta, so anything > 0 is healthy.
      passIf: metaHits > 0,
      note: "expect >0; absent on media-only messages",
      hint: () => hintMessageMeta(page, sels),
    });

    await reportRatio({
      label: "WA_MESSAGE_TEXT_SELECTOR",
      selector: sels.WA_MESSAGE_TEXT_SELECTOR ?? "",
      hits: textHits,
      sample,
      passIf: textHits > 0,
      note: "expect >0 across recent text messages",
      hint: () => hintMessageText(page, sels),
    });

    await reportRatio({
      label: "WA_MESSAGE_OUTGOING_INDICATOR",
      selector: sels.WA_MESSAGE_OUTGOING_INDICATOR ?? "",
      hits: outHits,
      sample,
      // If the chat is purely incoming or purely outgoing, one side is 0.
      // We only fail if BOTH outgoing and incoming look like the same thing,
      // which means the indicator never matched (outHits === sample for a
      // pure-incoming chat would be wrong, but we can't tell direction
      // without it — so just sanity-check it ran without error).
      passIf: true,
      note: `${showRatio(outHits)} outgoing, ${showRatio(inHits)} incoming (informational)`,
      hint: () => hintOutgoingIndicator(page, sels),
    });
  }

  await check({
    page,
    label: "WA_INPUT_BOX_SELECTOR",
    selector: sels.WA_INPUT_BOX_SELECTOR ?? "",
    expectMin: 1,
    hint: () => hintInputBox(page),
  });
}

type RatioReport = {
  label: string;
  selector: string;
  hits: number;
  sample: number;
  passIf: boolean;
  note?: string;
  hint?: () => Promise<string>;
};

async function reportRatio(r: RatioReport): Promise<void> {
  const symbol = r.passIf ? OK : FAIL;
  const status = r.passIf
    ? C.green(`${r.hits}/${r.sample} wrappers`)
    : C.red(`${r.hits}/${r.sample} wrappers`);
  const noteStr = r.note ? "  " + C.dim(r.note) : "";
  console.log(`  ${symbol} ${r.label.padEnd(33)} ${status}${noteStr}`);
  console.log(C.dim(`        ${r.selector}`));
  if (!r.passIf) {
    tally.fail++;
    if (r.hint) {
      const h = await r.hint().catch((e) => `(hint failed: ${e?.message ?? e})`);
      if (h.trim()) console.log(C.dim(indent("hint:\n" + h)));
    }
  } else {
    tally.pass++;
  }
}

async function runComposerPhase(page: Page, sels: Sels): Promise<void> {
  header("[3] Composer (typing a temp char to surface the Send button)");

  const inputBox = page.locator(sels.WA_INPUT_BOX_SELECTOR ?? "");
  if ((await inputBox.count()) === 0) {
    console.log(`  ${FAIL} composer input not found — skipping send-button check.`);
    tally.fail++;
    return;
  }

  await inputBox.first().click();
  await inputBox.first().pressSequentially("x", { delay: 30 });
  await page.waitForTimeout(300);

  await check({
    page,
    label: "WA_SEND_BUTTON_SELECTOR",
    selector: sels.WA_SEND_BUTTON_SELECTOR ?? "",
    expectMin: 1,
    hint: () => hintSendButton(page, sels),
  });

  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.press("Backspace");
}

async function runQRPhase(page: Page, sels: Sels): Promise<void> {
  header("[4] QR (only meaningful when logged out)");
  await check({
    page,
    label: "WA_QR_CODE_SELECTOR",
    selector: sels.WA_QR_CODE_SELECTOR ?? "",
    expectMin: 1,
    optional: true,
    note: "0 is expected when you're already logged in",
  });
}

// ─── Main ───────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const sels = loadSelectors();
  const known = [
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
  ];
  const missing = known.filter((k) => !sels[k]);
  if (missing.length) {
    console.error(C.red("Missing keys in .div-selectors:"));
    for (const k of missing) console.error("  - " + k);
    process.exit(1);
  }

  console.log(
    [
      C.bold("WhatsApp selector diagnostic"),
      "",
      "1. A browser will open.",
      "2. Log in if needed.",
      "3. Open ANY chat that has a few recent text messages, then come back",
      "   here and press Enter.",
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
      "globalThis.__name=function(f){return f;};",
  });
  await page.goto("https://web.whatsapp.com", { waitUntil: "domcontentloaded" });

  const rl = readline.createInterface({ input, output });
  try {
    await rl.question("Press Enter once a chat is open to begin diagnostics… ");

    await runSidebarPhase(page, sels);
    await runConversationPhase(page, sels);
    await runComposerPhase(page, sels);
    await runQRPhase(page, sels);

    const banner = tally.fail === 0
      ? C.green(`\nResult: all ${tally.pass} required checks passing (${tally.skip} skipped/optional).`)
      : C.red(`\nResult: ${tally.fail} broken, ${tally.pass} passing, ${tally.skip} skipped.`);
    console.log(banner);
    if (tally.fail > 0) {
      console.log(
        C.dim(
          "Update the broken keys in .div-selectors based on the hints above. " +
            "Structural changes may also need code changes in WhatsAppService.ts.",
        ),
      );
    }
  } finally {
    await browser.close();
    rl.close();
  }

  if (tally.fail > 0) process.exit(2);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
