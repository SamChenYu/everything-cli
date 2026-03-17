# everything-cli
```
├── autogitignore/        # Instant .gitignore setup
├── gemini/		          # Basic CLI wrapper for Gemini chat
├── tele/		          # CLI for Telegram using GramJS
└── whatsapp/		      # CLI for Whatsapp using Playwright + DOM reading
```

## Secrets scanning setup

```bash
pip3 install -r requirements.txt
# This should be done globally, otherwise hooks for secret scanning would appear inside the virtual env

./setup.sh
./verify-setup.sh
```
