# WhatsApp CLI

A terminal-based WhatsApp chat client that uses Playwright to read the  Whatsapp Web DOM in a Chromium browser. Built with Ink / React.

## Setup

```bash
npm install
npx playwright install chromium
cp .env.sample .env
```

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

WhatsApp Web uses obfuscated CSS class names that change on every deploy. All DOM selectors used by this tool are configured via environment variables in `.env` (see `.env.sample` for defaults and descriptions). If the app stops working after a WhatsApp update, inspect the page and update the selector values in your `.env`.
