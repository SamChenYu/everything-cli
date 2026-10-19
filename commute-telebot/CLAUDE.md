# CLAUDE.md

Guidance for working in this repo.

## What this is

A personal Telegram bot that pushes live **TfL 205 bus** arrivals and
**Hammersmith & City** line info during weekday commute windows, and answers
on-demand commands. Runs 24/7 on a small EC2 under `systemd` via long-polling
(no inbound ports, no webhook).

## Stack

- Python **3.12** (required — 3.13/3.14 have no prebuilt wheels for the pinned
  pydantic and will try to compile from source / need Rust; `setup.sh` fetches
  3.12 via `uv` to avoid this).
- `python-telegram-bot[job-queue]` 22.x — async; its built-in `JobQueue`
  (APScheduler wrapper) handles scheduling, so there is **no system cron**.
- `httpx` (async) against the free TfL Unified API (`api.tfl.gov.uk`).
- `pydantic-settings` (secrets from `.env`) + `PyYAML` (`config.yaml`).

## Layout

```
commute_bot/
  bot.py         # entry point: JobQueue scheduling, command handlers,
                 #   one-shot (--window), --dry-run, --whoami
  tfl.py         # async TfL client: bus_arrivals, tube_arrivals, line_status,
                 #   search_stops; Arrival dataclass (carries line + line_id + platform)
  formatting.py  # build_message / render_watch -> the Telegram message text
  config.py      # Secrets (.env) + Config/Window/BusWatch/TubeWatch (config.yaml)
  find_stops.py  # setup helper: search stops, dump live arrivals to verify direction
config.yaml      # windows/stops/filters (gitignored; copy from config.example.yaml)
.env             # TELEGRAM_TOKEN, CHAT_ID, TFL_APP_KEY (gitignored)
deploy/commute-bot.service   # systemd unit (User=ubuntu, /home/ubuntu/commute-telebot)
setup.sh         # uv + Python 3.12 venv + deps + seed config/.env
```

## Common commands

```bash
./setup.sh                                             # full env setup (uv, 3.12, deps)
./venv/bin/python -m commute_bot.bot --window morning --dry-run   # preview (no creds)
./venv/bin/python -m commute_bot.bot --window morning            # send one snapshot
./venv/bin/python -m commute_bot.bot                            # run the bot (scheduled + commands)
./venv/bin/python -m commute_bot.bot --whoami                   # discover CHAT_ID
./venv/bin/python -m commute_bot.find_stops "Stepney Green"     # find stop ids
./venv/bin/python -m commute_bot.find_stops --arrivals <id> --line 205   # verify direction
./venv/bin/python -m py_compile commute_bot/*.py               # quick syntax check
```

On the EC2, after editing `config.yaml` or `.env`:
```bash
sudo systemctl restart commute-bot
journalctl -u commute-bot -f
```

## Key concepts / gotchas

- **Windows & scheduling**: `config.yaml` defines named `windows` (morning/evening)
  with `start`/`end`/`every_minutes`; `Window.tick_times()` expands these to
  discrete `run_daily` jobs. `days` are name strings mapped in `DAY_NAME_TO_NUM`
  to PTB's **0=Sunday..6=Saturday** convention (Mon–Fri = 1–5). Changed in
  python-telegram-bot v20.
- **Watches** are a discriminated union on `kind`: `BusWatch` (stop_id + line +
  optional `destination_contains`) and `TubeWatch` (line status; add `stop_id` +
  `direction` to also show next-train times).
- **TfL field gotchas** (verified against live data):
  - `destinationName` is the terminus; `towards` is only the *next* major stop —
    filter on `destinationName`, not `towards`.
  - Bus direction is fixed by the physical stop's Naptan id (each direction is a
    separate stop point).
  - Tube direction is filtered by **`platformName` containing "Westbound"/
    "Eastbound"** — reliable even when `direction`/`destinationName` are null.
  - Tube filtering uses `line_id` (`hammersmith-city`), not `line` name
    ("Hammersmith & City").
- **Current stops**: morning `490000220W2` (Stepney Green, 205→Paddington via
  Marble Arch); evening `490000138L` (Liverpool St, 205→Bow Church); tube
  `940GZZLUSGN` (Stepney Green) and `940GZZLULVT` (Liverpool St).
- **Credentials-light modes**: `--dry-run` and `--whoami` avoid requiring the
  full `Secrets` (which needs `CHAT_ID`); the running bot and `--window` send
  do require it.
- **Delivery model**: scheduled pings go only to `CHAT_ID`. Command handlers
  (`/now`, `/status`, `/morning`, `/evening`) currently reply to *any* sender —
  add a `chat_id` allowlist guard in handlers to lock the bot to one user.
- **TfL app key** is optional at this volume; set `TFL_APP_KEY` in `.env` only if
  throttled.

## Conventions

- Async throughout; use the `httpx.AsyncClient` in `TflClient` (context-managed).
- Keep secrets in `.env` and config in `config.yaml` — never hard-code either;
  both are gitignored.
- Network/TfL errors are caught per-watch in `render_watch` so one failing feed
  doesn't kill the whole ping.
