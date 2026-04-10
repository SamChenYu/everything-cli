# everything-cli
```
├── autogitignore/        # Instant .gitignore setup
├── gemini/               # Basic CLI wrapper for Gemini chat
├── spotify/              # Terminal-based Spotify controller (TypeScript + Ink)
├── tcp-messenger/        # Basic TCP messenger (send/receive plain text)
├── tele/                 # CLI for Telegram using GramJS
└── whatsapp/             # CLI for WhatsApp using Playwright + DOM reading
```

## Secrets scanning setup

```bash
pip3 install -r requirements.txt
# This should be done globally, otherwise hooks for secret scanning would only appear inside the virtual env

./setup.sh
./verify-setup.sh
```
