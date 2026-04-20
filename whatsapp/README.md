# WhatsApp CLI

A terminal-based WhatsApp chat client that uses Playwright to read the  Whatsapp Web DOM in a Chromium browser. Built with Ink / React.

## Setup

```bash
npm install
npx playwright install chromium
```

DOM selectors live in the checked-in `.div-selectors` file (no env file needed).

## Running

```bash
npm start
```

On first run, a Chromium window will open and prompt you to scan the QR code with your phone (Settings → Linked Devices → Link a Device).

After a successful login the session is persisted in `.whatsapp-chrome-data/` so you won't need to scan the QR code again on subsequent runs.

## Usage

- **↑ / ↓** — navigate the chat list
- **Enter** — open selected chat / send composed message
- **`:q` + Enter** — go back to chat list
- **Ctrl+C** — exit

## Selectors

WhatsApp Web uses obfuscated CSS class names that change on every deploy. All DOM selectors used by this tool are configured in the `.div-selectors` file in the project root (checked into git — these are not sensitive). If the app stops working after a WhatsApp update, run `npm run check-selectors` — it opens WhatsApp Web, runs every selector against the live DOM, and prints a focused HTML snippet for any that no longer match so you can update them by hand.
