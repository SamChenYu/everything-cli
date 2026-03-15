# WhatsApp CLI

A terminal-based WhatsApp chat client that uses Playwright to automate [WhatsApp Web](https://web.whatsapp.com) in a Chromium browser.

## Setup

```bash
npm install
npx playwright install chromium
```

## Running

```bash
npm start
```

On first run, a Chromium window will open and prompt you to scan the QR code with your phone (Settings → Linked Devices → Link a Device).

After a successful login the session is saved to `.whatsapp-session` so you won't need to scan the QR code again on subsequent runs.

## Usage

- **Arrow keys / 1-5** — select a chat
- **Enter** — open selected chat / send composed message
- **`:q` + Enter** — go back to chat list
- **Ctrl+C** — exit
